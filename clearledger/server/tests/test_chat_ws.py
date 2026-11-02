import asyncio
import os

import pytest

from app.services.chat_ws import ChatConnectionManager, _NOTIFY_MAX_BYTES
from tests.test_chat_ws_lifetime import native_database, native_world


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.received = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def close(self, code=1000, reason=""):
        return None

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)
        self.received.set()


@pytest.mark.asyncio
async def test_notification_is_delivered_to_another_worker(native_world) -> None:
    sender = ChatConnectionManager()
    receiver = ChatConnectionManager()
    ws = FakeWebSocket()
    await native_world.connect(receiver, ws)
    receiver.subscribe(ws, native_world.channel)

    raw = sender._notification_payload(native_world.channel, {"type": "chat:message", "roomId": str(native_world.room.id)})
    await receiver._deliver_notification(raw)

    assert ws.messages == [{"type": "chat:message", "roomId": str(native_world.room.id), "channel": native_world.channel}]


@pytest.mark.asyncio
async def test_worker_ignores_own_postgres_notification(native_world) -> None:
    worker = ChatConnectionManager()
    ws = FakeWebSocket()
    await native_world.connect(worker, ws)
    worker.subscribe(ws, native_world.channel)

    raw = worker._notification_payload(native_world.channel, {"type": "chat:message"})
    await worker._deliver_notification(raw)

    assert ws.messages == []


@pytest.mark.asyncio
async def test_local_presence_without_shared_database(native_world) -> None:
    worker = ChatConnectionManager()
    ws = FakeWebSocket()

    identity, proof = await native_world.connect(worker, ws)
    assert ws.became_online is True
    assert await worker.online_user_ids() == {str(native_world.user.id)}
    assert await worker.is_online(str(native_world.user.id)) is True
    assert await worker.disconnect(ws) == (str(native_world.user.id), str(native_world.a.id), True)
    assert await worker.online_user_ids() == set()


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
async def test_postgres_delivers_between_worker_managers(native_world) -> None:
    sender = ChatConnectionManager()
    receiver = ChatConnectionManager()
    ws = FakeWebSocket()
    await native_world.connect(receiver, ws)
    receiver.subscribe(ws, native_world.channel)
    try:
        await sender.start(os.environ["DATABASE_URL"])
        await receiver.start(os.environ["DATABASE_URL"])
        await sender.broadcast(native_world.channel, {"type": "chat:message", "roomId": str(native_world.room.id)})
        await asyncio.wait_for(ws.received.wait(), timeout=2)
        assert ws.messages[-1]["type"] == "chat:message"
        assert ws.messages[-1]["channel"] == native_world.channel
    finally:
        await sender.stop()
        await receiver.stop()


@pytest.mark.asyncio
async def test_postgres_presence_is_shared_between_workers(native_world) -> None:
    sender = ChatConnectionManager()
    receiver = ChatConnectionManager()
    ws = FakeWebSocket()
    try:
        await sender.start(os.environ["DATABASE_URL"])
        await receiver.start(os.environ["DATABASE_URL"])
        await native_world.connect(sender, ws)
        assert await receiver.online_user_ids() == {str(native_world.user.id)}
        await sender.disconnect(ws)
        assert await receiver.online_user_ids() == set()
    finally:
        await sender.stop()
        await receiver.stop()
