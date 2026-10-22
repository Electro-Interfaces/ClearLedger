"""Повтор намерения создать бумагу не создаёт второй DocCard."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Company, DocCard, DocEvent, DocKind

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def payload_for(db, company_slug="gig"):
    company = (await db.execute(select(Company).where(Company.slug == company_slug))).scalar_one()
    kind = DocKind(company_id=company.id, code=f"replay_{uuid.uuid4().hex[:8]}", name="Тест бумаги")
    db.add(kind)
    await db.commit()
    return {"company_id": company_slug, "kind_id": str(kind.id), "title": "Тест экземпляра",
            "source": "manual", "source_ref": f"contract-document:{uuid.uuid4()}"}


async def test_concurrent_create_and_lost_response_replay_return_same_doc(auth_client, db):
    body = await payload_for(db)
    responses = await asyncio.gather(*[
        auth_client.post("/api/docs", json=body) for _ in range(2)])
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1
    replay = await auth_client.post("/api/docs", json=body)
    assert replay.status_code == 201 and replay.json()["id"] in ids
    count = (await db.execute(select(func.count()).select_from(DocCard).where(
        DocCard.source_ref == body["source_ref"]))).scalar_one()
    assert count == 1
    created_events = (await db.execute(select(func.count()).select_from(DocEvent).where(
        DocEvent.doc_id == uuid.UUID(next(iter(ids))), DocEvent.kind == "created"))).scalar_one()
    assert created_events == 1


async def test_reused_key_with_changed_content_is_conflict(auth_client, db):
    body = await payload_for(db)
    first = await auth_client.post("/api/docs", json=body)
    assert first.status_code == 201, first.text
    conflict = await auth_client.post("/api/docs", json={**body, "title": "Другая бумага"})
    assert conflict.status_code == 409, conflict.text


async def test_different_intentions_and_unkeyed_docs_remain_independent(auth_client, db):
    body = await payload_for(db)
    first = await auth_client.post("/api/docs", json=body)
    second = await auth_client.post("/api/docs", json={**body, "source_ref": f"contract-document:{uuid.uuid4()}"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    unkeyed = {**body, "source_ref": None}
    a = await auth_client.post("/api/docs", json=unkeyed)
    b = await auth_client.post("/api/docs", json=unkeyed)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
