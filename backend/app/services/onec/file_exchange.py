"""Файловый обмен ClearLedger → 1С (EnterpriseData XML).

Экспорт верифицированных записей в папку обмена, чтение feedback от 1С.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree
from sqlalchemy import select

from app.database import async_session
from app.models.models import OneCConnection, Entry, Counterparty, Organization

logger = logging.getLogger("onec.exchange")

ED_NS = "http://v8.1c.ru/edi/edi_stnd/EnterpriseData/1.5"
NSMAP = {"ed": ED_NS}


async def export_verified_entries(conn: OneCConnection) -> dict[str, Any]:
    """Генерирует EnterpriseData XML и кладёт в {exchange_path}/to_1c/."""
    exchange_path = Path(conn.exchange_path)
    to_1c = exchange_path / "to_1c"
    to_1c.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        # Получаем верифицированные записи с source=oneC
        result = await db.execute(
            select(Entry).where(
                Entry.company_id == conn.company_id,
                Entry.status == "verified",
                Entry.source_type != "oneC",  # Не реэкспортировать то, что пришло из 1С
            )
        )
        entries = list(result.scalars().all())

        if not entries:
            return {"status": "empty", "file_path": None, "entries_count": 0}

        # Кеши для контрагентов и организаций
        cp_result = await db.execute(
            select(Counterparty).where(Counterparty.company_id == conn.company_id)
        )
        counterparties = {str(cp.id): cp for cp in cp_result.scalars().all()}

        org_result = await db.execute(
            select(Organization).where(Organization.company_id == conn.company_id)
        )
        organizations = {str(org.id): org for org in org_result.scalars().all()}

    # Генерируем XML
    root = etree.Element("{%s}EnterpriseData" % ED_NS, nsmap=NSMAP)
    root.set("FormatVersion", "1.5")
    root.set("CreationDate", datetime.now(timezone.utc).isoformat())
    root.set("Source", "ClearLedger")

    exported = 0
    for entry in entries:
        try:
            doc_el = _entry_to_xml(entry, counterparties, organizations)
            if doc_el is not None:
                root.append(doc_el)
                exported += 1
        except Exception as e:
            logger.warning("Ошибка экспорта записи %s: %s", entry.id, e)

    if exported == 0:
        return {"status": "empty", "file_path": None, "entries_count": 0}

    # Сохраняем файл
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"clearledger_export_{timestamp}.xml"
    filepath = to_1c / filename

    tree = etree.ElementTree(root)
    tree.write(str(filepath), xml_declaration=True, encoding="UTF-8", pretty_print=True)

    logger.info("Экспортировано %d записей в %s", exported, filepath)

    return {
        "status": "success",
        "file_path": str(filepath),
        "entries_count": exported,
    }


def _entry_to_xml(
    entry: Entry,
    counterparties: dict[str, Any],
    organizations: dict[str, Any],
) -> etree._Element | None:
    """Конвертирует Entry в XML-элемент EnterpriseData."""
    metadata = entry.metadata_ or {}
    doc_type = metadata.get("_1c.docType") or entry.doc_type_id

    # Определяем тип документа 1С
    type_map = {
        "receipt": "ПоступлениеТоваровУслуг",
        "sales": "РеализацияТоваровУслуг",
        "payment-out": "ПлатежноеПоручениеИсходящее",
        "payment-in": "ПоступлениеНаРасчетныйСчет",
        "invoice-received": "СчетФактураПолученный",
        "invoice-issued": "СчетФактураВыданный",
    }

    onec_type = type_map.get(doc_type)
    if not onec_type:
        return None

    doc = etree.Element("{%s}%s" % (ED_NS, onec_type))

    # Основные поля
    _add_text(doc, "Номер", metadata.get("_1c.number") or entry.title[:20])
    _add_text(doc, "Дата", metadata.get("_1c.date") or entry.created_at.isoformat()[:10])

    # Контрагент
    cp_inn = metadata.get("counterpartyInn") or metadata.get("_1c.counterpartyInn")
    cp_name = metadata.get("counterparty") or metadata.get("_1c.counterparty")
    if cp_inn:
        cp_el = etree.SubElement(doc, "{%s}Контрагент" % ED_NS)
        _add_text(cp_el, "ИНН", cp_inn)
        if cp_name:
            _add_text(cp_el, "Наименование", cp_name)

    # Сумма
    amount = metadata.get("amount") or metadata.get("_1c.amount")
    if amount:
        _add_text(doc, "СуммаДокумента", str(amount))

    return doc


def _add_text(parent: etree._Element, tag: str, text: str) -> etree._Element:
    """Добавляет текстовый элемент."""
    el = etree.SubElement(parent, "{%s}%s" % (ED_NS, tag))
    el.text = text
    return el


async def check_feedback(conn: OneCConnection) -> dict[str, Any]:
    """Читает feedback-файлы из {exchange_path}/from_1c/."""
    exchange_path = Path(conn.exchange_path)
    from_1c = exchange_path / "from_1c"

    if not from_1c.exists():
        return {"status": "no_feedback", "files": []}

    feedback_files = []
    archive_dir = from_1c / "archive"

    for f in sorted(from_1c.glob("status_*.xml")):
        try:
            tree = etree.parse(str(f))
            root = tree.getroot()

            file_info = {
                "filename": f.name,
                "status": root.get("Status", "unknown"),
                "processed_count": int(root.get("ProcessedCount", "0")),
                "error_count": int(root.get("ErrorCount", "0")),
                "errors": [],
            }

            for err in root.findall(".//{%s}Error" % ED_NS) or root.findall(".//Error"):
                file_info["errors"].append({
                    "code": err.get("Code", ""),
                    "message": err.text or err.get("Message", ""),
                })

            feedback_files.append(file_info)

            # Архивируем обработанный файл
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(archive_dir / f.name))

        except Exception as e:
            logger.warning("Ошибка разбора feedback %s: %s", f.name, e)
            feedback_files.append({
                "filename": f.name,
                "status": "parse_error",
                "error": str(e),
            })

    return {
        "status": "ok" if feedback_files else "no_feedback",
        "files": feedback_files,
    }
