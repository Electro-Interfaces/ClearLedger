"""Authored contract definitions; execution belongs to the isolated root harness.

The module guard is NOT pre-import protection from ancestor conftest.py.
The runner must isolate conftest discovery before loading any of these modules.
"""
import os

import pytest

if os.environ.get("AUDIT_ROOT_COMMIT_ISOLATED") != "1":
    pytest.skip("requires owner-provided pre-import isolation", allow_module_level=True)

from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.audit import log_audit
from app.services import after_root_commit as deferred, notify

pytestmark = pytest.mark.asyncio


def _legacy_db():
    rows = []
    return SimpleNamespace(add=rows.append), rows


@pytest.mark.parametrize("actor", [None, SimpleNamespace(id=uuid4(), name="Синтетический актор")])
async def test_default_immediate_parity_and_system_actor(monkeypatch, actor):
    db, rows = _legacy_db()
    calls = []
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: calls.append((a, kw)))
    cid = uuid4()
    await log_audit(db, actor=actor, company_id=cid, action="sample.change",
                    target="Объект", details={"текст": "значение"})
    expected = 'Объект · {"текст": "значение"}'
    assert calls == [((cid, "sample.change"), {
        "who": actor.name if actor else None, "details": expected})]
    row, = rows
    assert row.company_id is cid and row.details == expected
    assert row.user_id == (str(actor.id) if actor else "system")
    assert row.user_name == (actor.name if actor else "Платформа")


@pytest.mark.parametrize("target,details,expected", [
    (None, None, None), ("", {}, None), ("Цель", {}, "Цель"),
    (None, {"a": [1]}, '{"a": [1]}'),
])
async def test_legacy_serialization_empty_and_unicode(monkeypatch, target, details, expected):
    db, rows = _legacy_db()
    calls = []
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: calls.append(kw))
    await log_audit(db, actor=None, company_id=uuid4(), action="sample",
                    target=target, details=details)
    assert rows[0].details == calls[0]["details"] == expected


@pytest.mark.parametrize("timing", ["immediate", "after_root_commit"])
async def test_serialization_error_precedes_add(monkeypatch, timing):
    engine = create_async_engine("postgresql+asyncpg://example:example@localhost/example_test")
    async with AsyncSession(engine) as db:
        calls = []
        monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: calls.append(a))
        with pytest.raises(TypeError):
            await log_audit(db, actor=None, company_id=uuid4(), action="sample",
                            details={"unserializable": object()}, notification_timing=timing)
        assert not db.new and not db.in_transaction() and not calls
    await engine.dispose()


async def test_invalid_mode_rejected_before_add_or_enqueue(monkeypatch):
    db, rows = _legacy_db()
    monkeypatch.setattr(deferred, "enqueue_audit_notification", lambda *a, **kw: pytest.fail("enqueued"))
    with pytest.raises(ValueError, match="timing"):
        await log_audit(db, actor=None, company_id=uuid4(), action="sample",
                        notification_timing="unknown")
    assert rows == []


async def test_payload_freezes_four_primitives_without_uuid_cast(monkeypatch):
    engine = create_async_engine("postgresql+asyncpg://example:example@localhost/example_test")
    db = AsyncSession(engine, expire_on_commit=True)
    cid = uuid4()
    actor = SimpleNamespace(id=uuid4(), name="До изменения")
    details = {"nested": ["исходное"]}
    calls = []
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: calls.append(a))
    await log_audit(db, actor=actor, company_id=cid, action="sample",
                    details=details, notification_timing="after_root_commit")
    actor.name = "После изменения"
    details["nested"].append("новое")
    queue = db.sync_session.info[deferred._STATE]
    _, payload = queue.items[queue.root][0]
    assert [f.name for f in fields(payload)] == ["company_id", "action", "who", "details"]
    assert payload.company_id is cid and type(payload.company_id) is type(cid)
    assert payload.who == "До изменения" and payload.details == '{"nested": ["исходное"]}'
    with pytest.raises(FrozenInstanceError):
        payload.who = "нельзя"
    assert not calls
    await db.close()
    assert deferred._STATE not in db.sync_session.info and not calls
    await engine.dispose()


async def test_optin_system_actor_snapshot():
    engine = create_async_engine("postgresql+asyncpg://example:example@localhost/example_test")
    async with AsyncSession(engine) as db:
        await log_audit(db, actor=None, company_id=uuid4(), action="sample",
                        notification_timing="after_root_commit")
        queue = db.sync_session.info[deferred._STATE]
        assert queue.items[queue.root][0][1].who is None
        row, = db.new
        assert row.user_id == "system" and row.user_name == "Платформа"
    await engine.dispose()


@pytest.mark.parametrize("configuration", ["multibind", "twophase", "override", "fake"])
async def test_unsafe_configuration_before_add(configuration):
    engine = create_async_engine("postgresql+asyncpg://example:example@localhost/example_test")
    if configuration == "multibind":
        from app.models import AuditEvent
        db = AsyncSession(engine, binds={AuditEvent: engine})
    elif configuration == "twophase":
        db = AsyncSession(engine, twophase=True)
    elif configuration == "override":
        class Override(Session):
            def get_bind(self, *args, **kwargs):
                return super().get_bind(*args, **kwargs)
        db = AsyncSession(engine, sync_session_class=Override)
    else:
        db, rows = _legacy_db()
    with pytest.raises(ValueError):
        await log_audit(db, actor=None, company_id=uuid4(), action="sample",
                        notification_timing="after_root_commit")
    if configuration == "fake":
        assert rows == []
    else:
        assert not db.new and deferred._STATE not in db.sync_session.info
        await db.close()
    await engine.dispose()
