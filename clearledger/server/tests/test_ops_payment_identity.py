"""Shared counterparty matching on real PostgreSQL; synthetic payments only."""
import asyncio
from decimal import Decimal
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models import Company, Counterparty, OpsPayment, OpsPeriodClose
from app.services import ops_payments

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def companies(db):
    suffix = uuid.uuid4().hex[:16]
    rows = [Company(name="Synthetic payment scope", slug="pay-" + suffix, profile_id="energy"),
        Company(name="Foreign payment scope", slug="pay-foreign-" + suffix, profile_id="energy")]
    db.add_all(rows)
    await db.commit()
    return rows


def parsed(name, amount=100):
    return {"payments": [{"period": "2026-01-01", "granularity": "month", "cost_item": "rent",
        "is_capital": False, "counterparty_name": name, "amount": amount, "object_numbers": ["SYNTHETIC-1"],
        "source_label": "synthetic test", "external_key": ops_payments._key("2026-01-01", "rent", False, name)}]}


async def result_row(db, company):
    return (await db.scalars(select(OpsPayment).where(OpsPayment.company_id == company.id)
        .execution_options(populate_existing=True))).one()


async def test_legal_form_stays_part_of_identity(db, companies):
    company, _ = companies
    llc = Counterparty(company_id=company.id, name='ООО "Синтетическая сеть"')
    corp = Counterparty(company_id=company.id, name='АО "Синтетическая сеть"')
    db.add_all([llc, corp]); await db.commit()
    result = await ops_payments.store(db, company.id, parsed("ООО «Синтетическая сеть»"))
    await db.commit()
    assert (await result_row(db, company)).counterparty_id == llc.id
    assert result["counterparties_matched"] == 1 and not result["identity_issues"]
    # A spelling without legal form is not authority to pick either company.
    result = await ops_payments.store(db, company.id, parsed("Синтетическая сеть"))
    await db.commit()
    bare = await db.scalar(select(OpsPayment).where(OpsPayment.company_id == company.id,
        OpsPayment.counterparty_name == "Синтетическая сеть"))
    assert bare.counterparty_id is None and result["counterparties_unmatched"] == 1


async def test_duplicate_name_is_explicitly_ambiguous_and_replay_never_creates_party(db, companies):
    company, _ = companies
    db.add_all([Counterparty(company_id=company.id, name='ООО "Дубль"'),
        Counterparty(company_id=company.id, name="ООО «Дубль»")])
    await db.commit()
    for _ in range(2):
        result = await ops_payments.store(db, company.id, parsed("ООО Дубль"))
        await db.commit()
        assert result["counterparties_ambiguous"] == 1 and result["counterparties_matched"] == 0
        assert result["identity_issues"][0]["status"] == "ambiguous"
        assert (await result_row(db, company)).counterparty_id is None
    assert await db.scalar(select(func.count()).select_from(OpsPayment).where(OpsPayment.company_id == company.id)) == 1
    assert await db.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.company_id == company.id)) == 2


async def test_group_and_foreign_company_never_match(db, companies):
    company, foreign = companies
    db.add_all([Counterparty(company_id=company.id, name="ООО Только группа", is_group=True),
        Counterparty(company_id=foreign.id, name="ООО Только группа")])
    await db.commit()
    result = await ops_payments.store(db, company.id, parsed("ООО Только группа"))
    await db.commit()
    assert result["counterparties_unmatched"] == 1
    assert (await result_row(db, company)).counterparty_id is None


async def test_common_manual_source_alias_is_respected(db, companies):
    company, _ = companies
    party = Counterparty(company_id=company.id, name="ООО Новое имя", manual_overrides=["name"],
        raw={"referenceIdentity": {"name": "ООО Прежнее имя"}})
    db.add(party); await db.commit()
    result = await ops_payments.store(db, company.id, parsed("ООО Прежнее имя"))
    await db.commit()
    assert result["counterparties_matched"] == 1
    assert (await result_row(db, company)).counterparty_id == party.id


async def test_replay_preserves_previous_valid_link_and_source_key(db, companies):
    company, _ = companies
    previous = Counterparty(company_id=company.id, name="ООО Источник")
    db.add(previous); await db.commit()
    first = await ops_payments.store(db, company.id, parsed("ООО Источник"))
    await db.commit()
    old = await result_row(db, company)
    payment_id, key = old.id, old.external_key
    previous.name = "ООО Переименовано"
    db.add(Counterparty(company_id=company.id, name="ООО Источник"))
    await db.commit()
    replay = await ops_payments.store(db, company.id, parsed("ООО Источник", 125))
    await db.commit()
    updated = await result_row(db, company)
    assert updated.id == payment_id and updated.external_key == key
    assert updated.counterparty_id == previous.id and updated.amount == Decimal("125")
    assert first["counterparties_matched"] == 1 and replay["counterparties_matched"] == 0
    assert replay["counterparties_retained"] == 1
    assert replay["identity_issues"][0]["status"] == "existing_link_retained"


async def test_cross_company_legacy_reference_is_not_retained_as_authority(db, companies):
    company, foreign = companies
    foreign_party = Counterparty(company_id=foreign.id, name="ООО Чужой источник")
    db.add(foreign_party); await db.flush()
    item = parsed("ООО Чужой источник")["payments"][0]
    db.add(OpsPayment(company_id=company.id, counterparty_id=foreign_party.id, **item))
    await db.commit()
    result = await ops_payments.store(db, company.id, parsed("ООО Чужой источник"))
    await db.commit()
    assert (await result_row(db, company)).counterparty_id is None
    assert result["counterparties_retained"] == 0


async def test_concurrent_replays_remain_one_payment_and_do_not_modify_closed_period(db, companies):
    from tests.conftest import _test_session_factory
    company, _ = companies
    party = Counterparty(company_id=company.id, name="ООО Параллельный источник")
    closed = OpsPeriodClose(company_id=company.id, period="2026-01-01", status="closed")
    db.add_all([party, closed]); await db.commit()
    async def replay(amount):
        async with _test_session_factory() as session:
            result = await ops_payments.store(session, company.id, parsed(party.name, amount))
            await session.commit()
            return result
    values = await asyncio.gather(replay(150), replay(175))
    row = await result_row(db, company)
    assert row.counterparty_id == party.id and row.amount in (Decimal("150"), Decimal("175"))
    assert all(value["counterparties_matched"] == 1 for value in values)
    await db.refresh(closed)
    assert closed.status == "closed"


async def test_identity_issues_are_bounded_without_losing_import_counts(db, companies):
    company, _ = companies
    payload = {"payments": [parsed(f"ООО Отсутствующее лицо {i}")["payments"][0] for i in range(101)]}
    result = await ops_payments.store(db, company.id, payload)
    await db.commit()
    assert result["saved"] == result["counterparties_unmatched"] == 101
    assert len(result["identity_issues"]) == 100 and result["identity_issues_truncated"] is True
    assert result["counterparties_matched"] == result["counterparties_retained"] == 0
