import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.models import Company, PartnerMessage, PartnerSpace
from app.services import partner_bridge, support_mirror

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_retry_survives_duplicate_and_does_not_replay_history(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    partner = PartnerSpace(company_id=company.id, role="client", code=uuid.uuid4().hex,
                           name="Приёмочный клиент", is_active=True)
    db.add(partner)
    await db.commit()
    payload = {"id": uuid.uuid4().hex, "body": "Приёмочное обращение", "topic": uuid.uuid4().hex}
    row, created = await partner_bridge.record_incoming(db, company.id, partner, payload)
    assert created and row.mirror_pending
    old = PartnerMessage(company_id=company.id, partner_id=partner.id, direction="in", body="История")
    db.add(old)
    await db.commit()
    mirror = AsyncMock(return_value=False)
    monkeypatch.setattr(support_mirror, "mirror_incoming", mirror)
    now = datetime.now(UTC)
    assert await support_mirror.deliver_pending(db, now, message_id=row.id) == 0
    assert row.mirror_attempts == 1 and row.mirror_pending
    assert row.mirror_next_at == now + timedelta(minutes=5)
    duplicate, created = await partner_bridge.record_incoming(db, company.id, partner, payload)
    assert not created and duplicate.id == row.id
    assert await support_mirror.deliver_pending(db, now, message_id=row.id) == 0
    mirror.assert_awaited_once()
    mirror.return_value = True
    assert await support_mirror.deliver_pending(db, now + timedelta(minutes=5), message_id=row.id) == 1
    assert row.mirror_attempts == 2 and not row.mirror_pending and row.mirrored_at
    assert not old.mirror_pending
    assert await support_mirror.deliver_pending(db, now + timedelta(hours=1), message_id=row.id) == 0


async def test_retry_has_stable_receiver_key_after_timeout(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    partner = PartnerSpace(company_id=company.id, role="client", code=uuid.uuid4().hex,
                           name="Приёмочный клиент", support_company_id=str(uuid.uuid4()))
    db.add(partner)
    await db.commit()
    row, _ = await partner_bridge.record_incoming(db, company.id, partner, {
        "id": uuid.uuid4().hex, "body": "После таймаута", "topic": uuid.uuid4().hex})
    monkeypatch.setattr(support_mirror.space_projection, "_target", AsyncMock(return_value=(
        SimpleNamespace(), SimpleNamespace(external_company_id="unused"), "synthetic-token")))
    monkeypatch.setattr(support_mirror.space_projection, "_internal_base_url", lambda *_: "http://support.test")
    calls = []
    async def post(_client, url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(200, json={"ok": True, "threadId": "synthetic-thread"})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    now = datetime.now(UTC)
    assert await support_mirror.deliver_pending(db, now, message_id=row.id) == 0
    assert "ReadTimeout" in row.mirror_error
    assert await support_mirror.deliver_pending(db, now + timedelta(minutes=5), message_id=row.id) == 1
    assert calls[0] == calls[1]
    assert calls[0]["externalId"] == f"partner:{company.id}:{row.id}"
    assert calls[0]["companyId"] == partner.support_company_id
    assert row.mirror_error is None


async def test_operator_reply_retries_the_saved_message(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    partner = PartnerSpace(company_id=company.id, role="client", code=uuid.uuid4().hex,
                           name="Приёмочный клиент", base_url="http://partner.test")
    db.add(partner)
    await db.commit()
    monkeypatch.setattr(partner_bridge, "partner_key", lambda _: "synthetic-key")
    calls = []
    async def post(_client, url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(503 if len(calls) == 1 else 200)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    external_id = uuid.uuid4().hex
    row = await partner_bridge.send(db, company.id, partner, self_code="desk", body="Ответ оператора", external_id=external_id)
    assert row.delivery_error and row.delivered_at is None
    repeated = await partner_bridge.send(db, company.id, partner, self_code="desk", body="Повтор не меняет текст", external_id=external_id)
    assert repeated.id == row.id and repeated.delivered_at and repeated.delivery_error is None
    assert calls[0] == calls[1]
    assert calls[1]["body"] == "Ответ оператора"
    await partner_bridge.send(db, company.id, partner, self_code="desk", body="Ответ", external_id=external_id)
    assert len(calls) == 2


async def test_state_failure_keeps_operator_outbox_retryable(db, monkeypatch):
    from fastapi import HTTPException
    from app.routers.space_bridge_router import SupportReply, support_reply

    company = (await db.scalars(select(Company).limit(1))).first()
    partner = PartnerSpace(company_id=company.id, role="client", code=uuid.uuid4().hex,
                           name="Приёмочный клиент", base_url="http://partner.test")
    db.add(partner)
    await db.commit()
    topic = await partner_bridge.ensure_topic(db, company.id, partner, uuid.uuid4().hex, title="Проверка состояния")
    await db.commit()
    monkeypatch.setattr(partner_bridge, "partner_key", lambda _: "synthetic-key")
    post = AsyncMock(return_value=httpx.Response(200))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    state = AsyncMock(side_effect=["Временный сбой", None])
    monkeypatch.setattr(partner_bridge, "send_state", state)
    payload = SupportReply(partner_code=partner.code, body="Ответ", topic=topic.code,
                           state="in_progress", external_id=uuid.uuid4().hex)
    with pytest.raises(HTTPException) as error:
        await support_reply(payload, company, db)
    assert error.value.status_code == 502
    assert (await support_reply(payload, company, db))["status"] == "sent"
    assert post.await_count == 1
    assert state.await_count == 2


async def test_new_client_message_reopens_both_sides_but_duplicate_does_not(db, monkeypatch):
    company = (await db.scalars(select(Company).limit(1))).first()
    partner = PartnerSpace(company_id=company.id, role="client", code=uuid.uuid4().hex, name="Приёмка")
    db.add(partner)
    await db.commit()
    code = uuid.uuid4().hex
    topic = await partner_bridge.ensure_topic(db, company.id, partner, code, title="Повторное открытие")
    await db.commit()
    await partner_bridge.apply_state(db, partner, code, state="closed", number=None)
    payload = {"id": uuid.uuid4().hex, "body": "Вопрос остался", "topic": code}
    await partner_bridge.record_incoming(db, company.id, partner, payload)
    assert topic.state == "open" and topic.closed_at is None
    await partner_bridge.apply_state(db, partner, code, state="closed", number=None)
    await partner_bridge.record_incoming(db, company.id, partner, payload)
    assert topic.state == "closed"
    partner.role = "vendor"
    partner.base_url = "http://partner.test"
    monkeypatch.setattr(partner_bridge, "partner_key", lambda _: "synthetic-key")
    monkeypatch.setattr(httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(200)))
    await partner_bridge.send(db, company.id, partner, self_code="gig", body="Возвращаем вопрос", topic=topic)
    assert topic.state == "open" and topic.closed_at is None
