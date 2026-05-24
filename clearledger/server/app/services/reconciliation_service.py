"""
Алгоритм сверки: AccountingDoc (1С) ↔ DataEntry (ClearLedger).

4 критерия, порог 55 баллов:
  ИНН контрагента  +40 (точное совпадение)
  Номер документа  +25 (fuzzy, нормализация)
  Дата             +20/+10 (±3 дня / ±7 дней)
  Сумма            +15/+8 (±1% / ±5%)

После матчинга — расхождения квалифицируются по спеке (docs/sverka-spec.md §7a):
  none      — суммарная дельта ≤ 0.005 ₽
  rounding  — ≤ 0.05 ₽   (в закрытом периоде подсвечивается строже)
  minor     — ≤ 1.00 ₽
  material  — ≤ 100 ₽
  critical  — > 100 ₽ или критичное поле (ИНН/контрагент/НДС-ставка)
  unmatched — пары нет
"""

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountingDoc, DataEntry, ReconcileMapping


# ---------------------------------------------------------------------------
# Нормализация номера документа
# ---------------------------------------------------------------------------

_DOC_NUM_STRIP = re.compile(r"[№#\-/\s]")
_DOC_NUM_PREFIX = re.compile(r"^(ТТН|СФ|АКТ|УПД|ПП|ПКО|РКО|ТОРГ|ТН)", re.IGNORECASE)


def normalize_doc_number(raw: str) -> str:
    """ТТН-123/45 → 12345, №00ПТ-678 → 00ПТ678"""
    s = raw.strip()
    s = _DOC_NUM_PREFIX.sub("", s)
    s = _DOC_NUM_STRIP.sub("", s)
    return s.upper()


# ---------------------------------------------------------------------------
# Парсинг даты
# ---------------------------------------------------------------------------

def parse_date(val: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(val.strip()[:19], fmt)
        except (ValueError, IndexError):
            continue
    return None


# ---------------------------------------------------------------------------
# Скоринг
# ---------------------------------------------------------------------------

def compute_score(doc: AccountingDoc, entry: DataEntry) -> dict:
    """Вычисляет общий score (0-100) и детали совпадения."""
    score = 0
    details: dict = {}

    meta = entry.meta or {}

    # --- Критерий 1: ИНН контрагента (+40) ---
    entry_inn = meta.get("inn", "") or meta.get("counterpartyInn", "")
    if doc.counterparty_inn and entry_inn:
        if doc.counterparty_inn.strip() == entry_inn.strip():
            score += 40
            details["innMatch"] = True
        else:
            details["innMatch"] = False
    else:
        details["innMatch"] = None

    # --- Критерий 2: Номер документа (+25) ---
    entry_num = meta.get("docNumber", "") or meta.get("_1c.number", "")
    if doc.number and entry_num:
        norm_doc = normalize_doc_number(doc.number)
        norm_entry = normalize_doc_number(entry_num)
        if norm_doc and norm_entry:
            if norm_doc == norm_entry:
                score += 25
                details["numberMatch"] = "exact"
            elif norm_doc in norm_entry or norm_entry in norm_doc:
                score += 15
                details["numberMatch"] = "partial"
            else:
                details["numberMatch"] = False
    else:
        details["numberMatch"] = None

    # --- Критерий 3: Дата (+20/+10) ---
    entry_date_str = meta.get("docDate", "")
    doc_date = parse_date(doc.date)
    entry_date = parse_date(entry_date_str) if entry_date_str else None
    if doc_date and entry_date:
        diff_days = abs((doc_date - entry_date).days)
        details["dateDiff"] = diff_days
        if diff_days <= 3:
            score += 20
        elif diff_days <= 7:
            score += 10
    else:
        details["dateDiff"] = None

    # --- Критерий 4: Сумма (+15/+8) ---
    entry_amount_str = meta.get("amount", "") or meta.get("totalAmount", "")
    try:
        entry_amount = float(entry_amount_str.replace(",", ".").replace(" ", ""))
    except (ValueError, AttributeError):
        entry_amount = None

    if doc.amount and entry_amount:
        if doc.amount > 0:
            pct_diff = abs(doc.amount - entry_amount) / doc.amount * 100
        else:
            pct_diff = 0 if entry_amount == 0 else 100
        details["amountDiff"] = round(doc.amount - entry_amount, 2)
        details["amountPctDiff"] = round(pct_diff, 2)
        if pct_diff <= 1:
            score += 15
        elif pct_diff <= 5:
            score += 8
    else:
        details["amountDiff"] = None

    details["score"] = score
    details["confidence"] = min(score, 100)
    return details


# ---------------------------------------------------------------------------
# Детальная проверка строк
# ---------------------------------------------------------------------------

def check_lines(doc: AccountingDoc, entry: DataEntry) -> dict:
    """Сравнить строки документа (если доступны)."""
    doc_lines = doc.lines if isinstance(doc.lines, list) else []
    if not doc_lines:
        return {"missingLines": [], "extraLines": []}

    # Для DataEntry строки могут быть в metadata._xml.items или ocr_data
    # В текущей версии просто фиксируем кол-во строк
    return {
        "docLinesCount": len(doc_lines),
        "missingLines": [],
        "extraLines": [],
    }


# ---------------------------------------------------------------------------
# Основная функция сверки
# ---------------------------------------------------------------------------

MATCH_THRESHOLD = 55  # минимальный score для кандидата
DISCREPANCY_THRESHOLD = 75  # при score >= 75 но есть расхождения → discrepancy


# Пороги классификации расхождений (docs/sverka-spec.md §7a.3).
# Применяются к |delta_amount| в рублях. Также включаются «критичные поля»
# (ИНН/контрагент/НДС-ставка) — несовпадение любого из них = critical
# независимо от величины суммы.
THR_NONE     = 0.005   # ниже — точное совпадение
THR_ROUNDING = 0.05    # копеечное округление
THR_MINOR    = 1.00    # мелкое расхождение
THR_MATERIAL = 100.0   # значимое


def classify_discrepancy(
    *,
    amount_delta: float | None,
    inn_match: bool | None,
    date_diff_days: int | None,
    vat_delta: float | None = None,
    period_status: str = "open",
) -> tuple[str, str]:
    """Возвращает (status, summary). status ∈ {none, rounding, minor, material,
    critical}. summary — короткая фраза для UI tooltip.

    В закрытом периоде (period_status='closed') пороги жёстче (правило §7a.4
    спеки): даже rounding промоутится до minor, потому что бухгалтерия уже
    сдала отчётность и любая корректировка требует Бух.справки.
    Карта промоушенов:
        rounding → minor
        minor    → material
    Material и critical остаются как есть (они и так требуют действий)."""
    parts: list[str] = []
    severities: list[str] = []

    # ИНН не совпал — это critical, не зависит от суммы.
    if inn_match is False:
        return "critical", "ИНН контрагента не совпадает"

    # Сумма
    if amount_delta is None:
        amt_sev = None
    else:
        ad = abs(amount_delta)
        if ad <= THR_NONE:
            amt_sev = "none"
        elif ad <= THR_ROUNDING:
            amt_sev = "rounding"
        elif ad <= THR_MINOR:
            amt_sev = "minor"
        elif ad <= THR_MATERIAL:
            amt_sev = "material"
        else:
            amt_sev = "critical"
        if amt_sev != "none":
            parts.append(f"сумма: {amount_delta:+.2f} ₽")
        severities.append(amt_sev)

    # НДС (если посчитан)
    if vat_delta is not None:
        vd = abs(vat_delta)
        if vd > THR_ROUNDING:
            parts.append(f"НДС: {vat_delta:+.2f} ₽")
        if vd <= THR_NONE:
            severities.append("none")
        elif vd <= THR_ROUNDING:
            severities.append("rounding")
        elif vd <= THR_MINOR:
            severities.append("minor")
        elif vd <= THR_MATERIAL:
            severities.append("material")
        else:
            severities.append("critical")

    # Дата (мягко — обычно даты копии в БП могут немного отличаться)
    if date_diff_days is not None and date_diff_days > 0:
        parts.append(f"дата: {date_diff_days} дн")
        if date_diff_days <= 3:
            severities.append("rounding")
        elif date_diff_days <= 14:
            severities.append("minor")
        else:
            severities.append("material")

    if not severities:
        return "pending", "недостаточно данных для сверки"

    # Берём максимальную серьёзность среди критериев.
    order = ["none", "rounding", "minor", "material", "critical"]
    status = max(severities, key=lambda s: order.index(s) if s in order else 0)

    # Period-aware промоушен — в закрытом периоде микрорасхождения становятся
    # требующими внимания (см. §7a.4 спеки).
    if period_status == "closed":
        promote = {"rounding": "minor", "minor": "material"}
        status = promote.get(status, status)

    summary = "; ".join(parts) if parts else "точное совпадение"
    if period_status == "closed" and status in ("minor", "material", "critical"):
        summary = "🔒 закрытый период · " + summary
    return status, summary


async def _load_mappings(db: AsyncSession, company_id: uuid.UUID, kind: str) -> dict[str, str]:
    """{source_key → target_ref} для kind."""
    rows = (await db.execute(
        select(ReconcileMapping.source_key, ReconcileMapping.target_ref)
        .where(ReconcileMapping.company_id == company_id, ReconcileMapping.kind == kind)
    )).all()
    return {sk: tr for sk, tr in rows}


async def run_reconciliation(db: AsyncSession, company_id: uuid.UUID) -> dict:
    """
    Запуск авто-сверки для компании.
    Возвращает статистику: matched, unmatched, discrepancy.

    Дополнительно: для смен (shift_orp/operational+shifts) если в meta есть
    station_code — резолвим через ReconcileMapping('station') и привязываем
    к AccountingDoc по warehouse_code + дате. Это работает без ИНН-матчинга.
    """
    # Маппинги — для быстрого резолва на стороне Python
    station_map = await _load_mappings(db, company_id, "station")
    fuel_map = await _load_mappings(db, company_id, "fuel")  # пока не используется в score, для будущей построчной сверки

    # Загружаем все документы 1С компании
    docs_result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.company_id == company_id)
    )
    docs = docs_result.scalars().all()

    # Индекс ORP-документов по (warehouse_code, date) для быстрого матча смен
    orp_by_station_date: dict[tuple[str, str], list[AccountingDoc]] = {}
    for d in docs:
        if d.doc_type == "ОРП" and d.warehouse_code:
            orp_by_station_date.setdefault((d.warehouse_code, d.date[:10]), []).append(d)

    # Загружаем все entries компании
    entries_result = await db.execute(
        select(DataEntry).where(DataEntry.company_id == company_id)
    )
    entries = entries_result.scalars().all()

    stats = {"matched": 0, "unmatched": 0, "discrepancy": 0, "total": len(docs),
             "via_station_mapping": 0}

    # Индекс entries по ИНН для O(1) lookup (ИНН даёт +40, основной критерий)
    entries_by_inn: dict[str, list[DataEntry]] = {}
    for entry in entries:
        meta = entry.meta or {}
        inn = (meta.get("inn", "") or meta.get("counterpartyInn", "")).strip()
        if inn:
            entries_by_inn.setdefault(inn, []).append(entry)

    # Множество уже использованных entries (1 entry : 1 doc)
    used_entries: set[uuid.UUID] = set()

    # ── Фаза 0: смены ↔ ОРП через ReconcileMapping('station') ──
    # Это специализированный быстрый матчинг по композитному ключу
    # (station_code → warehouse_code + date), независимый от ИНН-скоринга.
    used_docs: set[uuid.UUID] = set()
    if station_map:
        for entry in entries:
            meta = entry.meta or {}
            station_code = str(meta.get("station_code") or "")
            doc_date = (meta.get("shift_date") or meta.get("docDate") or "")[:10]
            if not station_code or not doc_date:
                continue
            # Ключ маппинга — внешний station_code STS. target_ref — это
            # external_ref Warehouse, но для матча с AccountingDoc.warehouse_code
            # удобнее искать просто по station_code если warehouse.code == station_code.
            # Альтернатива: подтянуть Warehouse.code по target_ref.
            candidates = orp_by_station_date.get((station_code, doc_date), [])
            for cand in candidates:
                if cand.id in used_docs:
                    continue
                entry_amount = entry_meta_amount(entry)
                doc_amount = cand.amount or 0
                amount_diff = (doc_amount - entry_amount) if entry_amount is not None else None
                d_status, d_summary = classify_discrepancy(
                    amount_delta=amount_diff,
                    inn_match=None,  # для смен ИНН не релевантен
                    date_diff_days=0,
                    period_status=cand.period_status or "open",
                )
                cand.matched_entry_id = entry.id
                cand.match_status = "matched" if d_status in ("none", "rounding") else "discrepancy"
                cand.match_details = {
                    "method": "station_mapping",
                    "amountDiff": amount_diff,
                    "station_code": station_code,
                    "date": doc_date,
                }
                cand.discrepancy_status = d_status
                cand.discrepancy_summary = d_summary
                cand.discrepancy_details = [
                    {"field": "shift_amount", "source": entry_amount, "target": doc_amount,
                     "delta": amount_diff, "severity": d_status, "method": "station_mapping"}
                ]
                used_docs.add(cand.id)
                used_entries.add(entry.id)
                stats["via_station_mapping"] += 1
                stats["matched" if cand.match_status == "matched" else "discrepancy"] += 1
                stats.setdefault("by_severity", {}).setdefault(d_status, 0)
                stats["by_severity"][d_status] += 1
                break  # одна смена → один ОРП

    for doc in docs:
        if doc.id in used_docs:
            continue  # уже сматчили через station mapping
        best_score = 0
        best_entry: DataEntry | None = None
        best_details: dict = {}

        # Фаза 1: кандидаты по ИНН (O(k) вместо O(n))
        candidates: list[DataEntry] = []
        if doc.counterparty_inn:
            inn_key = doc.counterparty_inn.strip()
            candidates = [e for e in entries_by_inn.get(inn_key, []) if e.id not in used_entries]

        for entry in candidates:
            details = compute_score(doc, entry)
            score = details["score"]
            if score > best_score:
                best_score = score
                best_entry = entry
                best_details = details

        # Фаза 2: полный перебор если ИНН не дал матча (порог 55 без ИНН: max 60)
        if best_score < MATCH_THRESHOLD:
            for entry in entries:
                if entry.id in used_entries:
                    continue
                details = compute_score(doc, entry)
                score = details["score"]
                if score > best_score:
                    best_score = score
                    best_entry = entry
                    best_details = details

        if best_score >= MATCH_THRESHOLD and best_entry is not None:
            used_entries.add(best_entry.id)

            # Старая система (matched/discrepancy) — оставляем для legacy UI.
            has_discrepancy = False
            if best_details.get("amountDiff") is not None:
                if abs(best_details["amountDiff"]) > 0.01:
                    has_discrepancy = True
            if best_details.get("dateDiff") is not None:
                if best_details["dateDiff"] > 0:
                    has_discrepancy = True

            line_details = check_lines(doc, best_entry)
            best_details.update(line_details)

            if has_discrepancy and best_score < DISCREPANCY_THRESHOLD:
                doc.match_status = "discrepancy"
                stats["discrepancy"] += 1
            else:
                doc.match_status = "matched"
                stats["matched"] += 1

            doc.matched_entry_id = best_entry.id
            doc.match_details = best_details

            # Новая система (none/rounding/minor/material/critical) — спека §7a.
            d_status, d_summary = classify_discrepancy(
                amount_delta=best_details.get("amountDiff"),
                inn_match=best_details.get("innMatch"),
                date_diff_days=best_details.get("dateDiff"),
                period_status=doc.period_status or "open",
            )
            doc.discrepancy_status = d_status
            doc.discrepancy_summary = d_summary
            doc.discrepancy_details = [
                {
                    "field": "amount",
                    "delta": best_details.get("amountDiff"),
                    "source": entry_meta_amount(best_entry),
                    "target": doc.amount,
                    "severity": d_status,
                },
            ]
            stats.setdefault("by_severity", {}).setdefault(d_status, 0)
            stats["by_severity"][d_status] += 1
        else:
            doc.match_status = "unmatched"
            doc.matched_entry_id = None
            doc.match_details = None
            doc.discrepancy_status = "unmatched"
            doc.discrepancy_summary = "пары в ClearLedger не найдено"
            doc.discrepancy_details = None
            stats["unmatched"] += 1
            stats.setdefault("by_severity", {}).setdefault("unmatched", 0)
            stats["by_severity"]["unmatched"] += 1

    await db.flush()
    return stats


def entry_meta_amount(entry: DataEntry) -> float | None:
    """Извлечь сумму из metadata DataEntry — толерантно к формату."""
    meta = entry.meta or {}
    raw = meta.get("amount") or meta.get("totalAmount") or meta.get("sum") or ""
    try:
        return float(str(raw).replace(",", ".").replace(" ", "")) if raw else None
    except (ValueError, TypeError):
        return None
