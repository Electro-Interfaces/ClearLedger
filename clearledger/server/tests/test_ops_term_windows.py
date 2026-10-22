import uuid

import pytest
from sqlalchemy import select

from app.models import Company, Contract, Counterparty, OpsContractTerm, OpsCostItem, Organization
from app.services.ops_terms import create_term, update_term

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def contract_and_cost(db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    cp = Counterparty(company_id=company.id, name="Тест ставок", inn="")
    org = Organization(company_id=company.id, name="Тест юрлица ставок", inn="", prefix="Т")
    db.add_all([cp, org])
    await db.flush()
    contract = Contract(company_id=company.id, number=uuid.uuid4().hex, date="2026-01-01",
                        type="Аренда", counterparty_id=cp.id, organization_id=org.id)
    db.add(contract)
    await db.flush()
    cost = (await db.execute(select(OpsCostItem.code).limit(1))).scalar_one()
    return company.id, contract.id, cost


async def test_overlapping_create_and_update_are_rejected(db):
    company, contract, cost = await contract_and_cost(db)
    base = {"contractId": str(contract), "costItem": cost, "scopeType": "company", "amountGross": 100}
    first = await create_term(db, company, {**base, "validFrom": "2026-02-01", "validTo": "2026-04-30"})
    with pytest.raises(ValueError, match="пересекается"):
        await create_term(db, company, {**base, "validFrom": "2026-04-30", "validTo": "2026-06-30"})
    second = await create_term(db, company, {**base, "validFrom": "2026-05-01", "validTo": "2026-12-31"})
    with pytest.raises(ValueError, match="пересекается"):
        await update_term(db, company, uuid.UUID(second["id"]), {"validFrom": "2026-04-01"})
    await db.refresh(await db.get(OpsContractTerm, uuid.UUID(second["id"])))
    assert (await db.get(OpsContractTerm, uuid.UUID(second["id"]))).valid_from == "2026-05-01"


async def test_new_version_closes_old_window_and_preserves_history(db):
    company, contract, cost = await contract_and_cost(db)
    old = await create_term(db, company, {"contractId": str(contract), "costItem": cost,
        "scopeType": "company", "validFrom": "2026-01-01", "amountGross": 100})
    new = await update_term(db, company, uuid.UUID(old["id"]),
                            {"validFrom": "2026-07-01", "amountGross": 200}, new_version=True)
    previous = await db.get(OpsContractTerm, uuid.UUID(old["id"]))
    assert previous.valid_to == "2026-06-30" and float(previous.amount_gross) == 100
    assert new["validFrom"] == "2026-07-01" and new["amountGross"] == 200


@pytest.mark.parametrize("start,end", [("2026-06-01", "2026-05-01"), ("2026-99-01", None)])
async def test_invalid_windows_are_rejected(db, start, end):
    company, contract, cost = await contract_and_cost(db)
    with pytest.raises(ValueError):
        await create_term(db, company, {"contractId": str(contract), "costItem": cost,
                          "validFrom": start, "validTo": end})
