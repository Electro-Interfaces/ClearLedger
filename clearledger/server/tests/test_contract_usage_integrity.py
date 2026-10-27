"""Мягкие ссылки защищают общий договор так же, как прямой FK.

Запускать только с выделенной TEST_DATABASE_URL: общий conftest создаёт схему.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    Company, Contract, ContractLink, Counterparty, DocCard, DocKind, DocRelation,
    Organization, Task, UserCompany,
)
from app.services.contract_usage import contract_usage, usage_by_contract

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def make_contract(db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    # ИНН свой на каждый прогон: пустой ИНН уникален в паре с компанией, и
    # остаток прошлого прогона в общей тестовой базе ронял все тесты файла.
    inn = str(uuid.uuid4().int)[:12]
    party = Counterparty(company_id=company.id, name="Тест связей", inn=inn)
    organization = Organization(company_id=company.id, name="Тест юрлица", inn=inn, prefix="Т")
    db.add_all([party, organization])
    await db.flush()
    contract = Contract(company_id=company.id, counterparty_id=party.id,
                        organization_id=organization.id, number=uuid.uuid4().hex,
                        date="2026-01-01", type="Аренда")
    db.add(contract)
    await db.flush()
    return contract


async def make_document(db, contract, *, subject=False, relation=False, attrs=False):
    kind = DocKind(company_id=contract.company_id, code=uuid.uuid4().hex, name="Тест бумаги")
    db.add(kind)
    await db.flush()
    card = DocCard(company_id=contract.company_id, kind_id=kind.id, title="Тест допсоглашения",
                   subject_ref=f"contract:{contract.id}" if subject else None,
                   attrs={"contract_id": str(contract.id)} if attrs else None)
    db.add(card)
    await db.flush()
    if relation:
        db.add(DocRelation(company_id=contract.company_id, doc_id=card.id,
                           kind="annex_of", target_ref=f"contract:{contract.id}"))
    return card


@pytest.mark.parametrize("link", ["relation", "attrs"])
async def test_annex_and_unfinished_document_prevent_contract_deletion(auth_client, db, link):
    contract = await make_contract(db)
    await make_document(db, contract, **{link: True})
    await db.commit()
    usage = await contract_usage(db, contract.id)
    assert next(item for item in usage if item["label"] == "Документы «Трека»")["count"] == 1
    bindings = await usage_by_contract(db, contract.company_id)
    assert "docs" in bindings[contract.id]["apps"]
    response = await auth_client.delete(f"/api/references/contracts/{contract.id}")
    assert response.status_code == 409, response.text
    assert await db.get(Contract, contract.id) is not None


async def test_one_document_counted_once_across_all_three_link_forms(db):
    contract = await make_contract(db)
    await make_document(db, contract, subject=True, relation=True, attrs=True)
    await db.flush()
    usage = await contract_usage(db, contract.id)
    assert next(item for item in usage if item["label"] == "Документы «Трека»")["count"] == 1


@pytest.mark.parametrize("link", ["task", "member", "application"])
async def test_non_document_soft_links_prevent_delete(auth_client, db, link):
    contract = await make_contract(db)
    if link == "task":
        db.add(Task(company_id=contract.company_id, title="Проверить договор",
                    subject_ref=f"contract:{contract.id}"))
    elif link == "member":
        membership = (await db.execute(select(UserCompany).where(
            UserCompany.company_id == contract.company_id).limit(1))).scalar_one()
        membership.contract_ids = [str(contract.id)]
    else:
        db.add(ContractLink(company_id=contract.company_id, contract_id=contract.id,
                            app_code="projects", project_ref=""))
    await db.commit()
    assert await contract_usage(db, contract.id)
    response = await auth_client.delete(f"/api/references/contracts/{contract.id}")
    assert response.status_code == 409, response.text


async def test_unused_contract_can_still_be_deleted(auth_client, db):
    contract = await make_contract(db)
    await db.commit()
    assert await contract_usage(db, contract.id) == []
    response = await auth_client.delete(f"/api/references/contracts/{contract.id}")
    assert response.status_code == 204, response.text
