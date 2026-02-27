"""
Алгоритм сверки: AccountingDoc (1С) ↔ DataEntry (ClearLedger).

4 критерия, порог 55 баллов:
  ИНН контрагента  +40 (точное совпадение)
  Номер документа  +25 (fuzzy, нормализация)
  Дата             +20/+10 (±3 дня / ±7 дней)
  Сумма            +15/+8 (±1% / ±5%)
"""

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountingDoc, DataEntry


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
            details["inn_match"] = True
        else:
            details["inn_match"] = False
    else:
        details["inn_match"] = None

    # --- Критерий 2: Номер документа (+25) ---
    entry_num = meta.get("docNumber", "") or meta.get("_1c.number", "")
    if doc.number and entry_num:
        norm_doc = normalize_doc_number(doc.number)
        norm_entry = normalize_doc_number(entry_num)
        if norm_doc and norm_entry:
            if norm_doc == norm_entry:
                score += 25
                details["number_match"] = "exact"
            elif norm_doc in norm_entry or norm_entry in norm_doc:
                score += 15
                details["number_match"] = "partial"
            else:
                details["number_match"] = False
    else:
        details["number_match"] = None

    # --- Критерий 3: Дата (+20/+10) ---
    entry_date_str = meta.get("docDate", "")
    doc_date = parse_date(doc.date)
    entry_date = parse_date(entry_date_str) if entry_date_str else None
    if doc_date and entry_date:
        diff_days = abs((doc_date - entry_date).days)
        details["date_diff_days"] = diff_days
        if diff_days <= 3:
            score += 20
        elif diff_days <= 7:
            score += 10
    else:
        details["date_diff_days"] = None

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
        details["amount_diff"] = round(doc.amount - entry_amount, 2)
        details["amount_pct_diff"] = round(pct_diff, 2)
        if pct_diff <= 1:
            score += 15
        elif pct_diff <= 5:
            score += 8
    else:
        details["amount_diff"] = None

    details["score"] = score
    return details


# ---------------------------------------------------------------------------
# Детальная проверка строк
# ---------------------------------------------------------------------------

def check_lines(doc: AccountingDoc, entry: DataEntry) -> dict:
    """Сравнить строки документа (если доступны)."""
    doc_lines = doc.lines if isinstance(doc.lines, list) else []
    if not doc_lines:
        return {"missing_lines": [], "extra_lines": []}

    # Для DataEntry строки могут быть в metadata._xml.items или ocr_data
    # В текущей версии просто фиксируем кол-во строк
    return {
        "doc_lines_count": len(doc_lines),
        "missing_lines": [],
        "extra_lines": [],
    }


# ---------------------------------------------------------------------------
# Основная функция сверки
# ---------------------------------------------------------------------------

MATCH_THRESHOLD = 55  # минимальный score для кандидата
DISCREPANCY_THRESHOLD = 75  # при score >= 75 но есть расхождения → discrepancy


async def run_reconciliation(db: AsyncSession, company_id: uuid.UUID) -> dict:
    """
    Запуск авто-сверки для компании.
    Возвращает статистику: matched, unmatched, discrepancy.
    """
    # Загружаем все документы 1С компании
    docs_result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.company_id == company_id)
    )
    docs = docs_result.scalars().all()

    # Загружаем все entries компании
    entries_result = await db.execute(
        select(DataEntry).where(DataEntry.company_id == company_id)
    )
    entries = entries_result.scalars().all()

    stats = {"matched": 0, "unmatched": 0, "discrepancy": 0, "total": len(docs)}

    # Множество уже использованных entries (1 entry : 1 doc)
    used_entries: set[uuid.UUID] = set()

    for doc in docs:
        best_score = 0
        best_entry: DataEntry | None = None
        best_details: dict = {}

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

            # Проверяем расхождения
            has_discrepancy = False
            if best_details.get("amount_diff") is not None:
                if abs(best_details["amount_diff"]) > 0.01:
                    has_discrepancy = True
            if best_details.get("date_diff_days") is not None:
                if best_details["date_diff_days"] > 0:
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
        else:
            doc.match_status = "unmatched"
            doc.matched_entry_id = None
            doc.match_details = None
            stats["unmatched"] += 1

    await db.flush()
    return stats
