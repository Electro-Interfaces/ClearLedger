import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Company, Counterparty
from app.services import channel_orchestrator


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_import_does_not_commit_partial_records_with_failure_event(db, monkeypatch):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    company_id = company.id
    await db.commit()
    channel = SimpleNamespace(id=uuid.uuid4(), name="Тест", template_id="reestr_contracts_payments")
    source = SimpleNamespace(id=uuid.uuid4(), company_id=company_id, source_type="manual_table", name="Тест")
    name = f"partial-{uuid.uuid4()}"
    event_name = f"event-{uuid.uuid4()}"

    async def find_source(*args):
        return source

    async def fail_after_insert(*args):
        db.add(Counterparty(company_id=company_id, name=name, inn=""))
        await db.flush()
        raise ValueError("Неоднозначная запись")

    async def publish_and_commit(db, channel, source, result):
        assert result["status"] == "error"
        db.add(Counterparty(company_id=company_id, name=event_name, inn=""))
        await db.commit()

    monkeypatch.setattr(channel_orchestrator, "_channel_source", find_source)
    monkeypatch.setattr(channel_orchestrator, "_dispatch", fail_after_insert)
    monkeypatch.setattr(channel_orchestrator, "_publish_sync_fact", publish_and_commit)
    with pytest.raises(ValueError, match="Неоднозначная"):
        await channel_orchestrator.run_channel(db, channel)
    count = await db.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.name == name))
    assert count == 0
    assert await db.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.name == event_name)) == 1
