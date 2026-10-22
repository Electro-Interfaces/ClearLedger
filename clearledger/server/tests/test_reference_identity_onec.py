"""Межисточниковое тождество: ручная карточка → offline-клиент 1С → тот же UUID."""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Company, Contract, Counterparty, Organization
from app.services.onec.odata_client import ENTITY_CONTRACTS, ENTITY_COUNTERPARTIES
from app.services.onec.sync_service import OneCSyncService
from app.services.reference_identity import IdentityConflict
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields

pytestmark = pytest.mark.asyncio(loop_scope="session")


class Source:
    def __init__(self, parties=(), contracts=()):
        self.rows = {ENTITY_COUNTERPARTIES: parties, ENTITY_CONTRACTS: contracts}

    async def iter_entity(self, entity, **kwargs):
        for row in self.rows.get(entity, ()):
            yield row


def log():
    return SimpleNamespace(items_processed=0, items_created=0, items_updated=0, items_errors=0)


async def context(db):
    company = Company(id=uuid.uuid4(), name="Тест сверки 1С", profile_id="energy",
                      slug=f"onec-identity-{uuid.uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    organization = Organization(company_id=company.id, name="Своя организация", inn="",
                                external_ref=str(uuid.uuid4()))
    db.add(organization)
    await db.flush()
    return SimpleNamespace(company_id=company.id, id=uuid.uuid4()), organization


def party_row(**kw):
    return {"Ref_Key": str(uuid.uuid4()), "Description": "Имя из 1С", "ИНН": "7766666666",
            "КПП": "776601001", **kw}


async def test_manual_identity_attached_to_onec_preserving_manual_fields(db):
    connection, organization = await context(db)
    row = party_row()
    party = Counterparty(company_id=connection.company_id, name="Ручное имя",
                         inn=row["ИНН"], kpp=row["КПП"], legal_address="Ручной адрес",
                         manual_overrides=["name", "legal_address"])
    db.add(party)
    await db.flush()
    doc = Contract(company_id=connection.company_id, counterparty_id=party.id,
                   organization_id=organization.id, number="74", date="2026-01-01",
                   type="СПоставщиком", amount_limit=123, manual_overrides=["amount_limit"])
    db.add(doc)
    await db.flush()
    source_doc = {"Ref_Key": str(uuid.uuid4()), "Owner_Key": row["Ref_Key"],
                  "Организация_Key": organization.external_ref, "Номер": "74",
                  "Дата": "2026-01-01T00:00:00", "ВидДоговора": "СПоставщиком", "Сумма": 999}
    source, service = Source([row], [source_doc]), OneCSyncService(db)
    stats = await service._sync_counterparties(source, connection, log())
    assert stats["created"] == 0 and stats["updated"] == 1
    assert party.external_ref == row["Ref_Key"] and party.name == "Ручное имя"
    stats = await service._sync_contracts(source, connection, log())
    assert stats["created"] == 0 and stats["updated"] == 1
    assert doc.external_ref == source_doc["Ref_Key"] and doc.amount_limit == 123
    before = snapshot_reference_fields(doc)
    doc.number, doc.date, doc.type = "Ручной номер", "2026-02-01", "Ручной вид"
    mark_reference_changes(doc, before)
    await service._sync_counterparties(source, connection, log())
    await service._sync_contracts(source, connection, log())
    assert doc.number == "Ручной номер" and doc.date == "2026-02-01" and doc.type == "Ручной вид"
    assert party.raw["Description"] == row["Description"]  # источник остаётся источником
    assert (await db.execute(select(func.count()).select_from(Counterparty).where(
        Counterparty.company_id == connection.company_id))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(Contract).where(
        Contract.company_id == connection.company_id))).scalar_one() == 1
    await db.rollback()


async def test_counterparty_other_external_ref_or_source_is_explicit_conflict(db):
    connection, _ = await context(db)
    row = party_row()
    party = Counterparty(company_id=connection.company_id, name="Тест", inn=row["ИНН"],
                         kpp=row["КПП"], external_ref=str(uuid.uuid4()))
    db.add(party)
    await db.flush()
    with pytest.raises(IdentityConflict, match="другим внешним ключом"):
        await OneCSyncService(db)._sync_counterparties(Source([row]), connection, log())
    party.external_ref = row["Ref_Key"]
    party.raw = {"referenceSource": {"connectionId": str(uuid.uuid4())}}
    await db.flush()
    with pytest.raises(IdentityConflict, match="другим источником"):
        await OneCSyncService(db)._sync_counterparties(Source([row]), connection, log())
    await db.rollback()


async def test_onec_duplicate_external_ref_is_not_first_candidate(db):
    connection, _ = await context(db)
    row = party_row()
    for inn in ("7755555555", "7744444444"):
        db.add(Counterparty(company_id=connection.company_id, name="Тест", inn=inn,
                            kpp="775501001", external_ref=row["Ref_Key"]))
    await db.flush()
    with pytest.raises(IdentityConflict, match="Неоднозначное"):
        await OneCSyncService(db)._sync_counterparties(Source([row]), connection, log())
    await db.rollback()


async def test_onec_incomplete_branch_identity_requires_confirmation(db):
    connection, _ = await context(db)
    row = party_row(КПП="")
    db.add(Counterparty(company_id=connection.company_id, name="Тест", inn=row["ИНН"], kpp=None))
    await db.flush()
    with pytest.raises(IdentityConflict, match="КПП"):
        await OneCSyncService(db)._sync_counterparties(Source([row]), connection, log())
    await db.rollback()


async def test_onec_contract_other_reference_is_not_overwritten(db):
    connection, organization = await context(db)
    row = party_row()
    service = OneCSyncService(db)
    await service._sync_counterparties(Source([row]), connection, log())
    party = (await db.execute(select(Counterparty).where(Counterparty.company_id == connection.company_id))).scalar_one()
    old_ref = str(uuid.uuid4())
    doc = Contract(company_id=connection.company_id, counterparty_id=party.id,
                   organization_id=organization.id, number="74", date="2026-01-01",
                   type="СПоставщиком", external_ref=old_ref)
    db.add(doc)
    await db.flush()
    incoming = {"Ref_Key": str(uuid.uuid4()), "Owner_Key": row["Ref_Key"],
                "Организация_Key": organization.external_ref, "Номер": "74",
                "Дата": "2026-01-01", "ВидДоговора": "СПоставщиком"}
    with pytest.raises(IdentityConflict, match="другим внешним ключом"):
        await service._sync_contracts(Source(contracts=[incoming]), connection, log())
    assert doc.external_ref == old_ref
    await db.rollback()


async def test_onec_same_contract_different_kind_requires_explicit_mapping(db):
    connection, organization = await context(db)
    row = party_row()
    service = OneCSyncService(db)
    await service._sync_counterparties(Source([row]), connection, log())
    party = (await db.execute(select(Counterparty).where(Counterparty.company_id == connection.company_id))).scalar_one()
    doc = Contract(company_id=connection.company_id, counterparty_id=party.id,
                   organization_id=organization.id, number="74", date="2026-01-01", type="Аренда")
    db.add(doc)
    await db.flush()
    incoming = {"Ref_Key": str(uuid.uuid4()), "Owner_Key": row["Ref_Key"],
                "Организация_Key": organization.external_ref, "Номер": "74",
                "Дата": "2026-01-01", "ВидДоговора": "СПоставщиком"}
    with pytest.raises(IdentityConflict, match="другой вид"):
        await service._sync_contracts(Source(contracts=[incoming]), connection, log())
    assert doc.external_ref is None
    await db.rollback()
