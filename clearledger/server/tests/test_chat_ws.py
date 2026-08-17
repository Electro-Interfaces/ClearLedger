import asyncio
import os

import pytest

from app.services.chat_ws import ChatConnectionManager, _NOTIFY_MAX_BYTES


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.received = asyncio.Event()

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)
        self.received.set()


@pytest.mark.asyncio
async def test_notification_is_delivered_to_another_worker() -> None:
    sender = ChatConnectionManager()
    receiver = ChatConnectionManager()
    ws = FakeWebSocket()
    receiver.subscribe(ws, "chat:room-1")

    raw = sender._notification_payload("chat:room-1", {"type": "chat:message", "roomId": "room-1"})
    await receiver._deliver_notification(raw)

    assert ws.messages == [{"type": "chat:message", "roomId": "room-1", "channel": "chat:room-1"}]


@pytest.mark.asyncio
async def test_worker_ignores_own_postgres_notification() -> None:
    worker = ChatConnectionManager()
    ws = FakeWebSocket()
    worker.subscribe(ws, "chat:room-1")

    raw = worker._notification_payload("chat:room-1", {"type": "chat:message"})
    await worker._deliver_notification(raw)

    assert ws.messages == []


def test_large_message_notification_is_compact() -> None:
    worker = ChatConnectionManager()
    raw = worker._notification_payload(
        "chat:room-1",
        {"type": "chat:message", "roomId": "room-1", "content": "я" * 10000},
    )

    assert len(raw.encode("utf-8")) <= _NOTIFY_MAX_BYTES
    assert '"truncated":true' in raw
    assert '"roomId":"room-1"' in raw


@pytest.mark.asyncio
async def test_postgres_delivers_between_worker_managers(setup_database) -> None:
    sender = ChatConnectionManager()
    receiver = ChatConnectionManager()
    ws = FakeWebSocket()
    receiver.subscribe(ws, "chat:room-pg")
    try:
        await sender.start(os.environ["DATABASE_URL"])
        await receiver.start(os.environ["DATABASE_URL"])
        await sender.broadcast("chat:room-pg", {"type": "chat:message", "roomId": "room-pg"})
        await asyncio.wait_for(ws.received.wait(), timeout=2)
        assert ws.messages[-1]["type"] == "chat:message"
        assert ws.messages[-1]["channel"] == "chat:room-pg"
    finally:
        await sender.stop()
        await receiver.stop()
