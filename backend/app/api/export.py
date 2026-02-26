"""Экспорт данных: 1С XML (CommerceML), Excel, CSV."""

from __future__ import annotations

import io
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Entry, User
from app.api.deps import get_current_user

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/1c")
async def export_1c_xml(
    company_id: str,
    status: str = Query("verified", description="Статус записей для выгрузки"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Выгрузка записей в XML-формат для 1С (CommerceML-совместимый)."""
    result = await db.execute(
        select(Entry)
        .where(Entry.company_id == company_id, Entry.status == status)
        .order_by(Entry.created_at)
    )
    entries = result.scalars().all()

    # CommerceML-подобный XML
    root = Element("КоммерческаяИнформация", attrib={
        "ВерсияСхемы": "2.10",
        "ДатаФормирования": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    })

    catalog = SubElement(root, "Каталог")
    SubElement(catalog, "Ид").text = company_id
    SubElement(catalog, "Наименование").text = f"ClearLedger: {company_id}"

    docs = SubElement(catalog, "Документы")
    for entry in entries:
        doc = SubElement(docs, "Документ")
        SubElement(doc, "Ид").text = str(entry.id)
        SubElement(doc, "Наименование").text = entry.title
        SubElement(doc, "Категория").text = entry.category_id
        SubElement(doc, "Подкатегория").text = entry.subcategory_id
        if entry.doc_type_id:
            SubElement(doc, "ТипДокумента").text = entry.doc_type_id
        SubElement(doc, "Статус").text = entry.status
        SubElement(doc, "Источник").text = entry.source_type
        SubElement(doc, "ДатаСоздания").text = entry.created_at.isoformat() if entry.created_at else ""

        meta = entry.metadata_ or {}
        if meta:
            props = SubElement(doc, "ЗначенияРеквизитов")
            for key, value in meta.items():
                prop = SubElement(props, "ЗначениеРеквизита")
                SubElement(prop, "Наименование").text = str(key)
                SubElement(prop, "Значение").text = str(value)

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode").encode("utf-8")
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="clearledger_{company_id}_{status}.xml"'},
    )


@router.get("/csv")
async def export_csv(
    company_id: str,
    status: str | None = None,
    category_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Выгрузка записей в CSV."""
    import csv

    q = select(Entry).where(Entry.company_id == company_id)
    if status:
        q = q.where(Entry.status == status)
    if category_id:
        q = q.where(Entry.category_id == category_id)
    q = q.order_by(Entry.created_at)

    result = await db.execute(q)
    entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "title", "category_id", "subcategory_id", "doc_type_id",
        "status", "source_type", "source_label", "created_at", "updated_at",
        "docNumber", "docDate", "counterparty", "amount",
    ])
    for e in entries:
        meta = e.metadata_ or {}
        writer.writerow([
            str(e.id), e.title, e.category_id, e.subcategory_id, e.doc_type_id or "",
            e.status, e.source_type, e.source_label,
            e.created_at.isoformat() if e.created_at else "",
            e.updated_at.isoformat() if e.updated_at else "",
            meta.get("docNumber", ""), meta.get("docDate", ""),
            meta.get("counterparty", ""), meta.get("amount", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM для Excel
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="clearledger_{company_id}.csv"'},
    )
