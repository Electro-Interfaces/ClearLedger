import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from app.models import Company, EzsSite, InboundEvent
from app.services import inbound_events, projects_process
from app.services.space_projection import ProjectionError

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_failed_transaction_does_not_expire_the_remaining_batch(db, monkeypatch):
    rows = [InboundEvent(provider="test", external_id=uuid.uuid4().hex, type=kind,
                         received_at=datetime.now(UTC) + timedelta(seconds=i))
            for i, kind in enumerate(["broken", "healthy", "healthy"])]
    db.add_all(rows)
    await db.commit()
    ids = [row.id for row in rows]
    seen = []

    async def handle(session, row):
        seen.append(row.id)
        if row.type == "broken":
            await session.execute(text("SELECT 1 / 0"))
        return "ok", None

    monkeypatch.setattr(inbound_events, "_handle", handle)
    assert await inbound_events.process_pending(db) == 3
    stored = (await db.scalars(select(InboundEvent).where(InboundEvent.id.in_(ids)))).all()
    by_id = {row.id: row for row in stored}
    assert seen == ids
    assert by_id[ids[0]].result == "failed"
    assert "division by zero" in by_id[ids[0]].error
    assert all(by_id[i].result == "ok" for i in ids[1:])
    assert await inbound_events.process_pending(db) == 0


async def test_subjects_from_facade_are_reconciled_only_in_authenticated_company(db, monkeypatch):
    companies = (await db.scalars(select(Company).limit(2))).all()
    sites = [EzsSite(company_id=c.id, title="ПРИЁМКА: событие проекта", stage="lead") for c in companies]
    db.add_all(sites)
    await db.flush()
    process_id = str(uuid.uuid4())
    event = InboundEvent(company_id=companies[0].id, provider="support", external_id=uuid.uuid4().hex,
                         type="case.closed", payload={"subject": process_id, "companyId": str(companies[1].id)})
    subjects = AsyncMock(return_value=[{"type": "ezs_site", "id": str(s.id)} for s in sites])
    reconcile = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(projects_process, "process_subjects", subjects)
    monkeypatch.setattr(projects_process, "reconcile", reconcile)
    assert await inbound_events._handle(db, event) == ("ok", None)
    subjects.assert_awaited_once_with(db, companies[0].id, process_id)
    reconcile.assert_awaited_once_with(db, companies[0].id, sites[0], user=None)
    await db.rollback()


async def test_ordinary_unbound_process_and_invalid_event_do_not_touch_projects(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    subjects = AsyncMock(return_value=[])
    monkeypatch.setattr(projects_process, "process_subjects", subjects)
    event = InboundEvent(company_id=company.id, type="case.stage_changed", payload={"subject": str(uuid.uuid4())})
    assert (await inbound_events._handle(db, event))[0] == "skipped"
    event.company_id = None
    assert (await inbound_events._handle(db, event))[0] == "skipped"
    event.company_id = company.id
    event.payload = {"subject": "../../another-process"}
    assert (await inbound_events._handle(db, event))[0] == "skipped"
    subjects.assert_awaited_once()


async def test_facade_failure_is_visible_and_does_not_prevent_next_event(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    db.add_all([
        InboundEvent(company_id=company.id, provider="test", external_id=uuid.uuid4().hex,
                     type="case.closed", payload={"subject": str(uuid.uuid4())}),
        InboundEvent(provider="test", external_id=uuid.uuid4().hex, type="unknown"),
    ])
    await db.commit()
    monkeypatch.setattr(projects_process, "process_subjects", AsyncMock(side_effect=ProjectionError("Недоступен")))
    assert await inbound_events.process_pending(db) == 2
    assert await inbound_events.process_pending(db) == 0


async def test_process_subjects_uses_facade_and_rejects_malformed_reply(db, monkeypatch):
    call = AsyncMock(return_value={"subjects": [{"type": "ezs_site", "id": str(uuid.uuid4())}]})
    monkeypatch.setattr(projects_process, "_call", call)
    process_id, company = str(uuid.uuid4()), uuid.uuid4()
    assert len(await projects_process.process_subjects(db, company, process_id)) == 1
    assert call.await_args.args[1:3] == (company, "GET")
    assert call.await_args.args[3].endswith(f"/{process_id}/subjects")
    call.return_value = {"subjects": {"type": "ezs_site"}}
    with pytest.raises(ProjectionError):
        await projects_process.process_subjects(db, company, process_id)
