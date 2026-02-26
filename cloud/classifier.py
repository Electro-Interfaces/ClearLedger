"""AI-классификатор документов.

Два режима:
1. Rule-based (по умолчанию, без API-ключа Anthropic)
2. Claude API (когда CLOUD_ANTHROPIC_API_KEY задан)
"""

from __future__ import annotations

import re
import logging
from typing import Any

from cloud.config import settings

logger = logging.getLogger("classifier")


async def classify_document(
    file_name: str,
    mime_type: str,
    extracted_text: str,
    extracted_fields: dict,
    company_id: str,
) -> dict[str, Any]:
    """Классифицирует документ и возвращает результат.

    Returns:
        {
            "classification": {"category_id", "subcategory_id", "doc_type_id", "confidence"},
            "normalized_metadata": {...},
            "decision": "accepted" | "needs_review" | "rejected",
            "model_version": str,
        }
    """
    if settings.anthropic_api_key:
        return await _classify_with_claude(
            file_name, mime_type, extracted_text, extracted_fields, company_id
        )
    return _classify_rule_based(
        file_name, mime_type, extracted_text, extracted_fields
    )


def _classify_rule_based(
    file_name: str,
    mime_type: str,
    extracted_text: str,
    extracted_fields: dict,
) -> dict[str, Any]:
    """Rule-based классификация (для разработки и offline)."""
    text_lower = extracted_text.lower()
    name_lower = file_name.lower()

    # ТТН
    if _match(text_lower, name_lower, ["товарно-транспортная", "ттн", "ttn"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("primary", "ttn", "ttn-gsm", 0.75, meta, "accepted", "rule-v1")

    # Акт сверки
    if _match(text_lower, name_lower, ["акт сверки", "акт_сверки"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("primary", "acts", "act-reconciliation", 0.7, meta, "accepted", "rule-v1")

    # Акт выполненных работ
    if _match(text_lower, name_lower, ["акт выполненных", "акт_выполненных"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("primary", "acts", "act-work", 0.7, meta, "accepted", "rule-v1")

    # Счёт-фактура
    if _match(text_lower, name_lower, ["счёт-фактура", "счет-фактура", "сф-", "invoice"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("primary", "invoices", "invoice-standard", 0.7, meta, "accepted", "rule-v1")

    # Платёжное поручение
    if _match(text_lower, name_lower, ["платежное поручение", "платёжное", "п/п"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("financial", "payments", "payment-order", 0.7, meta, "accepted", "rule-v1")

    # Договор
    if _match(text_lower, name_lower, ["договор", "контракт", "contract"]):
        meta = _extract_doc_fields(extracted_text)
        return _result("legal", "contracts", "contract-standard", 0.65, meta, "accepted", "rule-v1")

    # 1С XML (CommerceML)
    if "commerceml" in text_lower or "1c" in name_lower:
        return _result("primary", "oneC", "oneC-exchange", 0.8, {}, "accepted", "rule-v1")

    # Excel
    if mime_type in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      "application/vnd.ms-excel"):
        return _result("reporting", "reports", "report-table", 0.5, {}, "needs_review", "rule-v1")

    # Скан/фото — на ревью
    if mime_type.startswith("image/"):
        return _result("primary", "scans", None, 0.3, {}, "needs_review", "rule-v1")

    # Не распознано — на ревью
    meta = _extract_doc_fields(extracted_text) if extracted_text else {}
    return _result("uncategorized", "other", None, 0.2, meta, "needs_review", "rule-v1")


async def _classify_with_claude(
    file_name: str,
    mime_type: str,
    extracted_text: str,
    extracted_fields: dict,
    company_id: str,
) -> dict[str, Any]:
    """Классификация через Claude API."""
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        prompt = f"""Ты — система классификации документов ClearLedger.

Документ: {file_name} ({mime_type})
Текст (первые 5000 символов):
{extracted_text[:5000]}

Извлечённые поля: {extracted_fields}

Компания: {company_id}

Классифицируй документ. Верни JSON:
{{
  "category_id": "primary|financial|legal|personnel|reporting|administrative",
  "subcategory_id": "конкретная подкатегория",
  "doc_type_id": "тип документа или null",
  "confidence": 0.0-1.0,
  "decision": "accepted|needs_review|rejected",
  "title": "сгенерированный заголовок документа",
  "docNumber": "номер документа или null",
  "docDate": "дата документа YYYY-MM-DD или null",
  "counterparty": "контрагент или null",
  "counterparty_inn": "ИНН или null",
  "amount": "сумма или null"
}}

Только JSON, без пояснений."""

        response = await client.messages.create(
            model=settings.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        import json
        text = response.content[0].text.strip()
        # Убираем markdown-обёртку если есть
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)

        meta = {}
        for key in ("title", "docNumber", "docDate", "counterparty", "counterparty_inn", "amount"):
            if data.get(key):
                meta[key] = str(data[key])

        return _result(
            data.get("category_id", "uncategorized"),
            data.get("subcategory_id", "other"),
            data.get("doc_type_id"),
            data.get("confidence", 0.5),
            meta,
            data.get("decision", "needs_review"),
            f"claude-{settings.model}",
        )

    except Exception as e:
        logger.error(f"Claude API ошибка: {e}")
        # Fallback на rule-based
        return _classify_rule_based(file_name, mime_type, extracted_text, extracted_fields)


def _match(text: str, filename: str, keywords: list[str]) -> bool:
    return any(kw in text or kw in filename for kw in keywords)


def _extract_doc_fields(text: str) -> dict[str, str]:
    """Извлекает базовые поля из текста (regex)."""
    meta: dict[str, str] = {}

    # Номер документа
    m = re.search(r'[№#]\s*(\d[\d\-/]*)', text)
    if m:
        meta["docNumber"] = m.group(1)

    # Дата
    m = re.search(r'(\d{2}[./]\d{2}[./]\d{4})', text)
    if m:
        parts = re.split(r'[./]', m.group(1))
        meta["docDate"] = f"{parts[2]}-{parts[1]}-{parts[0]}"

    # Сумма
    m = re.search(r'(?:итого|сумма|всего)[:\s]*(\d[\d\s]*[.,]\d{2})', text, re.IGNORECASE)
    if m:
        meta["amount"] = m.group(1).replace(" ", "").replace(",", ".")

    # ИНН
    m = re.search(r'ИНН[:\s]*(\d{10,12})', text)
    if m:
        meta["counterparty_inn"] = m.group(1)

    return meta


def _result(
    cat: str, sub: str, doc_type: str | None,
    confidence: float, meta: dict, decision: str, model: str,
) -> dict[str, Any]:
    title = meta.get("title", "")
    if not title:
        parts = []
        if doc_type:
            parts.append(doc_type)
        if meta.get("docNumber"):
            parts.append(f"№{meta['docNumber']}")
        if meta.get("docDate"):
            parts.append(f"от {meta['docDate']}")
        if meta.get("counterparty"):
            parts.append(f"— {meta['counterparty']}")
        title = " ".join(parts) if parts else f"{cat}/{sub}"
        meta["title"] = title

    return {
        "classification": {
            "category_id": cat,
            "subcategory_id": sub,
            "doc_type_id": doc_type,
            "confidence": confidence,
        },
        "normalized_metadata": meta,
        "decision": decision,
        "model_version": model,
    }
