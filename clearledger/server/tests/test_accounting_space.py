"""«Бухгалтерия» пространства: сопряжение выгрузки с карточками (чтение).

Проверяется то, из-за чего экран вообще нужен: обе оси различаются (сопряжение и
проверка), статусы считаются из данных, а правка сверенного поля делает проверку
устаревшей сама — без ручной отметки.
"""
import json
import uuid

import pytest
from sqlalchemy import delete, select

from app.models import (
    Company,
    Contract,
    ContractLocation,
    Counterparty,
    DataEntry,
    Organization,
    ServiceLocation,
)
from app.services.accounting_space import digest

pytestmark = pytest.mark.asyncio

BATCH = "test-accounting-20260930-v1"
FILE = "Контрагенты, Договоры за 9 месяцев 2026.xlsx"
SHA = "a" * 64


def _entry(company_id, *, status, counterparty, contract, meta_extra=None, **kw):
    meta = {
        "_accountingReconciliationStatus": status,
        "_accountingBatchId": BATCH,
        "_accountingRecordKind": "export_row",
        "_accountingSourceAsOf": "2026-09-30",
        "_accountingSourceSha256": SHA,
        "_accountingSourceKey": uuid.uuid4().hex,
        "_accountingSourceKeyType": "text_fingerprint_not_1c_guid",
        "Контрагент в бухгалтерии": counterparty,
        "Договор или основание": contract,
        "Файл источника": FILE,
        "Лист источника": "Лист_1",
        "Строки источника": "7",
        "Период источника": "01.01.2026–30.09.2026",
        "Статус сопряжения": status,
    }
    meta.update(meta_extra or {})
    return DataEntry(
        company_id=company_id, title=f"{status} · {counterparty}",
        category_id="primary", subcategory_id="contracts",
        status=kw.get("entry_status", "recognized"), source="upload",
        source_label="Бухгалтерия · тест", layer="raw",
        # Исторический префикс стоит у ВСЕХ записей партии: статус по нему определять нельзя.
        source_id="acct-unmatched:" + meta["_accountingSourceKey"], meta=meta,
    )


def _recon(contract: Contract, *, status="matched", verification="partial",
           relation="same_contract", source_number=None, source_date=None,
           location_ids=(), hash_override=None):
    fields = {"number": contract.number, "date": contract.date,
              "counterparty_id": str(contract.counterparty_id),
              "type_code": contract.type_code}
    return {
        "entity_type": "contract", "entity_id": str(contract.id), "relation": relation,
        "status": status, "verification_status": verification,
        "source_number": source_number if source_number is not None else contract.number,
        "source_date": source_date if source_date is not None else contract.date,
        "target_values": fields,
        "target_checked_hash": hash_override or digest(fields),
        "snapshot_at": "2026-10-28T15:16:03+00:00",
        "location_ids": list(location_ids),
        "subject_status": "подтвержден предмет",
        "inn_kpp_checked": False, "original_document_checked": False,
    }


@pytest.fixture
async def space(db):
    """Срез пространства: площадка, контрагент, два договора и четыре строки источника."""
    company = (await db.execute(select(Company).where(Company.slug == "rushydro"))).scalar_one()
    org = Organization(company_id=company.id, name="ПАО «РусГидро»", inn="2460066195")
    db.add(org)
    party = Counterparty(company_id=company.id, name="Перспектива ООО", inn="7811111111", kpp="781101001")
    db.add(party)
    await db.flush()
    location = ServiceLocation(id="test-loc-1", company_id=company.id, code="НСП-0294",
                               name="ЭЗС Приморская", type="ev_charging", address="Приморский пр., 1")
    db.add(location)
    rent = Contract(company_id=company.id, counterparty_id=party.id, organization_id=org.id,
                    number="41-09/ЭЗС-23", date="2023-09-25", type="Аренда", type_code="rent")
    energy = Contract(company_id=company.id, counterparty_id=party.id, organization_id=org.id,
                      number="41-09/ЭЗС-23", date="2023-09-25", type="Энергоснабжение",
                      type_code="energy_supply")
    db.add_all([rent, energy])
    await db.flush()
    db.add_all([
        ContractLocation(company_id=company.id, contract_id=rent.id, location_id=location.id),
        ContractLocation(company_id=company.id, contract_id=energy.id, location_id=location.id),
    ])

    matched = _entry(company.id, status="matched", counterparty="Перспектива ООО",
                     contract="41-09/ЭЗС-23 от 25.09.2023", meta_extra={
                         "_accountingReconciliations": json.dumps(
                             [_recon(rent, location_ids=[location.id]),
                              _recon(energy, location_ids=[location.id])], ensure_ascii=False),
                         "_accountingTargetEntityIds": json.dumps([str(rent.id), str(energy.id)]),
                     })
    # Расхождение: в выгрузке дата другая, идентичность договора при этом не оспаривается.
    differing = _entry(company.id, status="matched", counterparty="Аскон НАО",
                       contract="15082024 от 15.08.2024", meta_extra={
                           "_accountingReconciliations": json.dumps(
                               [_recon(energy, verification="differences",
                                       source_date="2024-08-15")], ensure_ascii=False),
                       })
    related = _entry(company.id, status="related", counterparty="Перспектива ООО",
                     contract="Соглашение № 1 от 01.02.2024", meta_extra={
                         "_accountingReconciliations": json.dumps(
                             [_recon(rent, status="related", verification="not_checked",
                                     relation="annex_of")], ensure_ascii=False),
                     })
    unmatched = _entry(company.id, status="unmatched", counterparty="Хамадеев С. Ф. ИП",
                       contract="03-10/2023 от 03.10.2023", entry_status="new", meta_extra={
                           "_accountingVerificationStatus": "not_checked",
                           "Кандидаты в пространстве": "Не найдены",
                           "Номера ЭЗС из бухгалтерии": "#N/A",
                           "Основание разбора": "не сопоставлен контрагент",
                       })
    candidate = _entry(company.id, status="candidate", counterparty="Новая ООО",
                       contract="99 от 01.01.2026", entry_status="new", meta_extra={
                           "_accountingReconciliations": "[]",
                           "_accountingTargetEntityIds": "[]",
                       })
    db.add_all([matched, differing, related, unmatched, candidate])
    # Коммит, а не flush: запросы API идут своей сессией и незакоммиченных данных
    # другой транзакции не видят — тест проверял бы пустой ответ.
    await db.commit()
    ids = {"entries": [matched.id, differing.id, related.id, unmatched.id, candidate.id],
           "contracts": [rent.id, energy.id], "party": party.id,
           "location": location.id, "org": org.id, "company": company.id}
    yield {"company_id": str(company.id), "rent": rent, "energy": energy,
           "location": location, "records": {"matched": matched, "unmatched": unmatched}}
    # Чистим за собой сами: после commit откат уже ничего не вернёт, а БД общая
    # для всего прогона — оставленные строки сломали бы соседние тесты.
    await db.execute(delete(DataEntry).where(DataEntry.id.in_(ids["entries"])))
    await db.execute(delete(ContractLocation).where(
        ContractLocation.contract_id.in_(ids["contracts"])))
    await db.execute(delete(Contract).where(Contract.id.in_(ids["contracts"])))
    await db.execute(delete(Counterparty).where(Counterparty.id == ids["party"]))
    await db.execute(delete(ServiceLocation).where(ServiceLocation.id == ids["location"]))
    await db.execute(delete(Organization).where(Organization.id == ids["org"]))
    await db.commit()


async def test_summary_counts_both_axes(auth_client, space):
    """Плитки: статусы сопряжения и состояние проверки — независимые оси."""
    r = await auth_client.get("/api/accounting/space/summary",
                              params={"company_id": space["company_id"]})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["source_rows"] == 5
    assert s["by_status"] == {"matched": 2, "related": 1, "unmatched": 1, "candidate": 1}
    assert s["differences"] == 1          # дата выгрузки против карточки
    assert s["stale"] == 0                # карточки после сверки не менялись
    assert s["linked_contracts"] == 2     # сопряжены оба договора площадки
    assert s["as_of"] == ["2026-09-30"]
    # Периметр выгрузки оговорён: «нет строки» ≠ «нет договора в бухгалтерии».
    assert "периметра" in s["scope"] or "период" in s["scope"]
    assert s["space"]["contracts"] >= 2


async def test_records_filters_share_one_selection(auth_client, space):
    """Отбор плитки и список считаются из одного набора, пагинация знает полный total."""
    cid = space["company_id"]
    all_rows = await auth_client.get("/api/accounting/space/records", params={"company_id": cid})
    assert all_rows.json()["total"] == 5
    unmatched = await auth_client.get("/api/accounting/space/records",
                                      params={"company_id": cid, "status": "unmatched"})
    body = unmatched.json()
    assert body["total"] == 1 and body["items"][0]["status"] == "unmatched"
    assert body["items"][0]["status_label"] == "Не сопряжено"
    # Статус не выводится из префикса source_id: он «acct-unmatched:» у всех записей.
    matched = await auth_client.get("/api/accounting/space/records",
                                    params={"company_id": cid, "status": "matched"})
    assert matched.json()["total"] == 2
    diff = await auth_client.get("/api/accounting/space/records",
                                 params={"company_id": cid, "verification": "differences"})
    assert diff.json()["total"] == 1
    page = await auth_client.get("/api/accounting/space/records",
                                 params={"company_id": cid, "limit": 2, "offset": 0})
    assert page.json()["total"] == 5 and len(page.json()["items"]) == 2
    found = await auth_client.get("/api/accounting/space/records",
                                  params={"company_id": cid, "search": "Хамадеев"})
    assert found.json()["total"] == 1
    # Страницы покрывают весь отбор без потерь и повторов: вся партия приехала одной
    # транзакцией с одинаковым created_at, и порядок обязан быть детерминированным.
    seen: list[str] = []
    for offset in range(0, 5, 2):
        page = await auth_client.get("/api/accounting/space/records",
                                     params={"company_id": cid, "limit": 2, "offset": offset})
        seen.extend(r["id"] for r in page.json()["items"])
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_record_card_shows_both_sides(auth_client, space):
    """Карточка: сторона бухгалтерии, сторона пространства и перечень сверенных полей."""
    r = await auth_client.get(
        f"/api/accounting/space/records/{space['records']['matched'].id}",
        params={"company_id": space["company_id"]})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["source_side"]["file"] == FILE
    assert card["source_side"]["key_type"] == "text_fingerprint_not_1c_guid"
    # Признака проведения в 1С выгрузка не содержит — остаётся неизвестным, не False.
    assert card["source_side"]["posted"] is None
    assert len(card["links"]) == 2
    link = card["links"][0]
    # «Сверены поля» — только то, что сошлось со значением выгрузки. Снимок полей
    # карточки лежит отдельно и сверкой не называется: он про устаревание.
    assert link["checked_fields"] == ["date", "number"]
    assert link["snapshot_fields"] == ["counterparty_id", "date", "number", "type_code"]
    assert {f["field"]: f["equal"] for f in link["compared_fields"]} == {
        "number": True, "date": True}
    assert link["card"]["exists"] is True
    assert link["inn_kpp_checked"] is False
    assert link["original_document_checked"] is False
    assert link["card"]["locations"][0]["code"] == "НСП-0294"


async def test_edit_of_checked_field_makes_verification_stale(auth_client, db, space):
    """Правка сверенного поля устаревляет проверку; непроверявшееся поле — нет."""
    cid = space["company_id"]
    space["rent"].comment = "правка непроверявшегося поля"
    await db.commit()
    s = (await auth_client.get("/api/accounting/space/summary",
                               params={"company_id": cid})).json()
    assert s["stale"] == 0, "комментарий в состав сверки не входил"

    space["rent"].number = "41-09/ЭЗС-23-новый"
    await db.commit()
    s = (await auth_client.get("/api/accounting/space/summary",
                               params={"company_id": cid})).json()
    assert s["stale"] == 2, "обе строки с этим договором ждут повторной сверки"
    stale = await auth_client.get("/api/accounting/space/records",
                                  params={"company_id": cid, "verification": "stale"})
    assert stale.json()["total"] == 2
    card = (await auth_client.get(
        f"/api/accounting/space/records/{space['records']['matched'].id}",
        params={"company_id": cid})).json()
    assert any(l["stale"] and l["verification_label"] == "Нужна повторная сверка"
               for l in card["links"])


async def test_object_report_separates_rent_and_energy(auth_client, space):
    """Отчёт по объекту: аренда земли и получение э/э — отдельные основания."""
    r = await auth_client.get("/api/accounting/space/objects",
                              params={"company_id": space["company_id"]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    o = items[0]
    assert o["code"] == "НСП-0294"
    assert o["has_rent"] and o["has_energy"]
    assert len(o["rent"]) == 1 and len(o["energy"]) == 1
    assert o["contracts_count"] == 2
    assert o["with_source"] == 2  # на оба договора легли строки выгрузки


async def test_sources_journal_keeps_unknown_export_date(auth_client, space):
    """Журнал источников: партия, период, SHA-256; дата выгрузки из 1С не выдумывается."""
    r = await auth_client.get("/api/accounting/space/sources",
                              params={"company_id": space["company_id"]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    b = items[0]
    assert b["batch_id"] == BATCH and b["file"] == FILE and b["sha256"] == SHA
    assert b["rows"] == 5 and b["by_status"]["unmatched"] == 1
    assert b["exported_at"] is None
    assert b["loaded_at"] is not None


async def test_entity_links_reused_by_card(auth_client, space):
    """Сопряжения карточки доступны её собственному экрану тем же ответом."""
    r = await auth_client.get("/api/accounting/space/links", params={
        "company_id": space["company_id"], "entity_type": "contract",
        "entity_id": str(space["rent"].id)})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2  # сопряжённый договор и связанное соглашение
    assert {i["status"] for i in items} == {"matched", "related"}
    assert items[0]["source"]["file"] == FILE


async def test_other_company_is_not_visible(auth_client, db, space):
    """Изоляция: записи компании не видны при запросе другой компании."""
    other = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    r = await auth_client.get("/api/accounting/space/summary",
                              params={"company_id": str(other.id)})
    assert r.status_code == 200
    assert r.json()["source_rows"] == 0
    bad = await auth_client.get(
        f"/api/accounting/space/records/{space['records']['matched'].id}",
        params={"company_id": str(other.id)})
    assert bad.status_code == 404
