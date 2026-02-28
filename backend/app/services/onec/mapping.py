"""Маппинг OData-сущностей 1С → модели ClearLedger.

Справочники (Фаза 1):
  Catalog_Контрагенты → Counterparty
  Catalog_Организации → Organization
  Catalog_Номенклатура → Nomenclature
  Catalog_ДоговорыКонтрагентов → Contract
  Catalog_Склады → Warehouse
  Catalog_БанковскиеСчета → BankAccount

Документы (Фаза 2):
  Document_ПоступлениеТоваровУслуг → AccountingDoc (receipt)
  Document_РеализацияТоваровУслуг → AccountingDoc (sales)
  Document_ПлатежноеПоручениеИсходящее → AccountingDoc (payment-out)
  Document_СчетФактураПолученный → AccountingDoc (invoice-received)
  Document_СчетФактураВыданный → AccountingDoc (invoice-issued)
"""

from __future__ import annotations

from typing import Any


# ── Справочники (Фаза 1) ──────────────────────────────────

def map_counterparty(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_Контрагенты → Counterparty."""
    inn = (item.get("ИНН") or "").strip()
    kpp = (item.get("КПП") or "").strip() or None
    name = (item.get("Description") or item.get("Наименование") or "").strip()

    # Определяем тип: ЮЛ / ФЛ / ИП
    cp_type = "ЮЛ"
    legal_form = (item.get("ЮридическоеФизическоеЛицо") or "").strip()
    if legal_form == "ФизическоеЛицо":
        cp_type = "ФЛ"
    elif len(inn) == 12:
        cp_type = "ИП"

    return {
        "inn": inn,
        "kpp": kpp,
        "name": name,
        "short_name": (item.get("НаименованиеСокращенное") or name)[:200],
        "type": cp_type,
        "external_ref": item.get("Ref_Key"),
    }


def map_organization(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_Организации → Organization."""
    return {
        "inn": (item.get("ИНН") or "").strip(),
        "kpp": (item.get("КПП") or "").strip() or None,
        "ogrn": (item.get("ОГРН") or "").strip() or None,
        "name": (item.get("Description") or item.get("НаименованиеПолное") or "").strip(),
        "external_ref": item.get("Ref_Key"),
    }


def map_nomenclature(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_Номенклатура → Nomenclature."""
    # Ставка НДС из 1С
    vat_str = item.get("СтавкаНДС") or ""
    vat_rate = 20.0
    if "10" in vat_str:
        vat_rate = 10.0
    elif "0" in vat_str or "БезНДС" in vat_str:
        vat_rate = 0.0

    unit = item.get("ЕдиницаИзмерения_Key") or item.get("Код_ЕдиницыИзмерения") or "796"
    unit_label = item.get("ЕдиницаИзмерения") or "шт"
    if isinstance(unit_label, dict):
        unit_label = unit_label.get("Description", "шт")

    return {
        "code": (item.get("Code") or item.get("Код") or "").strip(),
        "name": (item.get("Description") or item.get("Наименование") or "").strip(),
        "unit": str(unit),
        "unit_label": str(unit_label),
        "vat_rate": vat_rate,
        "external_ref": item.get("Ref_Key"),
    }


def map_contract(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_ДоговорыКонтрагентов → Contract (частичный маппинг, без resolve FK)."""
    return {
        "number": (item.get("НомерДоговора") or item.get("Code") or "").strip(),
        "date": item.get("Дата") or item.get("Date"),
        "type": (item.get("ВидДоговора") or "Прочее").strip(),
        "counterparty_ref": item.get("Owner_Key"),  # Ref_Key контрагента — resolve позже
        "external_ref": item.get("Ref_Key"),
    }


def map_warehouse(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_Склады → Warehouse."""
    return {
        "code": (item.get("Code") or item.get("Код") or "").strip(),
        "name": (item.get("Description") or item.get("Наименование") or "").strip(),
        "address": (item.get("Адрес") or "").strip() or None,
        "type": "warehouse",
        "external_ref": item.get("Ref_Key"),
    }


def map_bank_account(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog_БанковскиеСчета → BankAccount."""
    return {
        "number": (item.get("НомерСчета") or "").strip(),
        "bank_name": (item.get("Банк") or "").strip() if isinstance(item.get("Банк"), str) else "",
        "bik": (item.get("БИК") or "").strip() if isinstance(item.get("БИК"), str) else "",
        "corr_account": (item.get("КоррСчет") or "").strip() or None,
        "currency": (item.get("ВалютаДенежныхСредств") or "RUB").strip(),
        "organization_ref": item.get("Owner_Key"),  # Ref_Key организации — resolve позже
        "external_ref": item.get("Ref_Key"),
    }


# ── Документы (Фаза 2) ────────────────────────────────────

DOC_TYPE_MAP: dict[str, str] = {
    "Document_ПоступлениеТоваровУслуг": "receipt",
    "Document_РеализацияТоваровУслуг": "sales",
    "Document_ПлатежноеПоручениеИсходящее": "payment-out",
    "Document_СчетФактураПолученный": "invoice-received",
    "Document_СчетФактураВыданный": "invoice-issued",
}

DOC_LINE_EXPAND: dict[str, str] = {
    "Document_ПоступлениеТоваровУслуг": "Товары",
    "Document_РеализацияТоваровУслуг": "Товары",
}


def map_document(entity_name: str, item: dict[str, Any]) -> dict[str, Any]:
    """OData-документ → AccountingDoc (без resolve FK)."""
    doc_type = DOC_TYPE_MAP.get(entity_name, "receipt")
    posted = item.get("Posted", False)

    return {
        "external_id": item.get("Ref_Key", ""),
        "doc_type": doc_type,
        "number": (item.get("Number") or item.get("Номер") or "").strip(),
        "date": item.get("Date") or item.get("Дата"),
        "counterparty_ref": item.get("Контрагент_Key"),
        "counterparty_name": "",  # resolve через external_ref lookup
        "counterparty_inn": "",
        "organization_ref": item.get("Организация_Key"),
        "organization_name": "",
        "amount": float(item.get("СуммаДокумента") or item.get("ДокументСумма") or 0),
        "vat_amount": float(item.get("СуммаНДС") or 0),
        "status_1c": "Проведён" if posted else "Не проведён",
        "warehouse_ref": item.get("Склад_Key"),
    }


def map_doc_lines(lines_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Табличная часть Товары → AccountingDocLine[]."""
    result = []
    for line in lines_data:
        nom = line.get("Номенклатура") or {}
        nom_name = nom.get("Description", "") if isinstance(nom, dict) else str(nom)
        nom_code = nom.get("Code", "") if isinstance(nom, dict) else ""

        qty = float(line.get("Количество") or 0)
        price = float(line.get("Цена") or 0)
        amount = float(line.get("Сумма") or qty * price)
        vat_amount = float(line.get("СуммаНДС") or 0)

        # Ставка НДС
        vat_str = str(line.get("СтавкаНДС") or "20")
        vat_rate = 20.0
        if "10" in vat_str:
            vat_rate = 10.0
        elif "0" in vat_str or "Без" in vat_str:
            vat_rate = 0.0

        result.append({
            "nomenclature_code": nom_code,
            "nomenclature_name": nom_name,
            "quantity": qty,
            "price": price,
            "amount": amount,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
        })
    return result
