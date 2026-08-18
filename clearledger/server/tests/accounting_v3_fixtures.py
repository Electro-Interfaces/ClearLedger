from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import AccountingBusinessGroup, BusinessShift
from app.services.accounting_contract_v3 import (
    accounting_packet_uuid,
    alias_hash,
    business_key_hash,
    business_projection_hash,
    canonical_hash,
)


@dataclass(frozen=True)
class AccountingV3Fixture:
    packet: dict
    shift: BusinessShift
    group: AccountingBusinessGroup


def accounting_v3_fixture(
    *,
    company_id: uuid.UUID,
    station_id: int,
    fact_at: datetime,
    policy_id: uuid.UUID,
    policy_revision: int,
    policy_hash: str,
    food: bool = False,
    document_kind: str | None = None,
    revision: int = 1,
    fact_origin: str = "edge",
) -> AccountingV3Fixture:
    day = fact_at.date()
    station = str(station_id)
    company = str(company_id).lower()
    shift_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"test-business-shift:{company}:{station}:{day}",
    )
    shift = BusinessShift(
        id=shift_id, company_id=company_id, company_key=company,
        station_id=station, business_date=day, status="resolved",
    )
    group = AccountingBusinessGroup(
        id=uuid.uuid4(), company_id=company_id, business_shift_id=shift_id,
        business_key_hash=business_key_hash(shift_id, company, station),
        packet_uuid=accounting_packet_uuid(shift_id), status="active",
    )
    internal = f"SYN-{station}-{day.isoformat()}"
    ose = f"OSE-{station}-{day.isoformat()}"
    common_attributes = {
        "company_id": company, "station_id": station,
        "business_date": day.isoformat(), "ose": ose,
    }
    aliases = [{
        "Algorithm": "business-shift-common-alias-v1",
        "AliasHash": alias_hash("business-shift-common-alias-v1", common_attributes),
        "Attributes": common_attributes,
    }]
    if fact_origin == "edge":
        edge_attributes = {
            "company_id": company, "station_id": station,
            "internal_shift_no": internal, "business_date": day.isoformat(),
        }
        aliases.append({
            "Algorithm": "business-shift-alias-v1",
            "AliasHash": alias_hash("business-shift-alias-v1", edge_attributes),
            "Attributes": edge_attributes,
        })
    aliases.sort(key=lambda row: (row["Algorithm"], row["AliasHash"]))

    retail_source = f"retail-{station}-{day.isoformat()}"
    retail_content = {
        "Проведен": False,
        "Продажи": ([{
            "НомерСтроки": 1, "НоменклатураUUID": "dish-synthetic-001",
            "КлассSKU": "Общепит", "АналитикаПродажи": "Сопутствующие товары",
            "Количество": "1.000", "Сумма": "122.00", "НДС": "22.00",
            "СтавкаНДС": "22",
        }] if food else []),
        "Возвраты": [],
        "Оплаты": [{"НомерСтроки": 1, "Вид": "Безнал", "Сумма": "122.00"}],
    }
    documents = []
    recipes = []
    nsi = []
    components = []
    if food:
        production_content = {
            "Проведен": False,
            "ВыпускБлюд": [{
                "НоменклатураUUID": "dish-synthetic-001",
                "Количество": "1.000", "Себестоимость": "10.000000",
            }],
        }
        documents.append({
            "ПорядокГруппы": 1, "Тип": "production_release",
            "ИсточникUUID": "production-synthetic-001", "РольВГруппе": "evidence",
            "SourceHash": canonical_hash(production_content),
            "Содержимое": production_content,
        })
        recipe = {
            "БлюдоUUID": "dish-synthetic-001",
            "ИдентификаторТТК": "ttk-synthetic-001", "РевизияТТК": 1,
            "BundleHash": "1" * 64,
            "Ингредиенты": [{
                "НомерСтроки": 1, "ИнгредиентUUID": "ingredient-synthetic-001",
                "Количество": "0.100", "Единица": "kg",
            }],
        }
        recipes.append(recipe)
        nsi.extend([
            {"Тип": "Номенклатура", "ИсточникUUID": "dish-synthetic-001", "Наименование": "Блюдо", "КлассSKU": "Общепит"},
            {"Тип": "Номенклатура", "ИсточникUUID": "ingredient-synthetic-001", "Наименование": "Ингредиент", "КлассSKU": "Сопутка"},
        ])
        components.append({
            "Порядок": 1, "Тип": "assembly",
            "ИсточникUUID": f"assembly:{retail_source}",
        })
    documents.append({
        "ПорядокГруппы": len(documents) + 1,
        "Тип": document_kind or "retail_sale_sidegoods",
        "ИсточникUUID": retail_source, "РольВГруппе": "materialized",
        "SourceHash": canonical_hash(retail_content), "Содержимое": retail_content,
    })
    components.append({
        "Порядок": len(components) + 1, "Тип": "retail",
        "ИсточникUUID": retail_source,
    })

    shift_payload = {
        "НомерВнутренний": internal, "ОСЭ": ose,
        "ОткрытаВ": (fact_at - timedelta(hours=8)).isoformat(timespec="seconds"),
        "ЗакрытаВ": fact_at.isoformat(timespec="seconds"),
        "ЧасовойПояс": "Europe/Moscow",
    }
    sources = []
    for kind in (
        "cheques", "cost_snapshot", "exact_ttk", "payments",
        "production_snapshot", "returns", "shift_closure",
    ):
        required = kind in {"cheques", "payments", "shift_closure"} or food
        if required:
            sources.append({
                "Тип": kind, "Требуется": True, "Статус": "ready",
                "Количество": 1, "SourceHash": canonical_hash({"kind": kind}),
            })
        else:
            sources.append({
                "Тип": kind, "Требуется": False, "Статус": "not_applicable",
                "Количество": 0, "SourceHash": None,
            })
    packet = {
        "ВерсияФормата": "3", "ВерсияКонтракта": "3.0.0",
        "ИдентификаторПакета": str(group.packet_uuid),
        "BusinessShiftID": str(shift_id), "BusinessShiftAliases": aliases,
        "BusinessDate": day.isoformat(), "CompanyID": company,
        "StationID": station, "BusinessKeyHash": group.business_key_hash,
        "FactOrigin": fact_origin, "TransportProducer": "central_ledger",
        "РевизияПакета": revision, "ИдентификаторПолитики": str(policy_id),
        "РевизияПолитики": policy_revision, "ХешПолитики": policy_hash,
        "ХешПакета": "", "UnicodeNormalization": "NFC",
        "ПолнотаГруппы": {
            "Версия": "1", "Статус": "complete", "Источники": sources,
            "ОжидаемыеКомпоненты": components,
        },
        "Смена": shift_payload, "НСИ": nsi, "ТТК": recipes,
        "Документы": documents,
    }
    packet["ХешПакета"] = business_projection_hash(packet)
    return AccountingV3Fixture(packet, shift, group)
