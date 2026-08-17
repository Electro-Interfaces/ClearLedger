"""WebSocket-соединения чата и межпроцессная доставка через PostgreSQL."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from contextlib import suppress

import asyncpg
from fastapi import WebSocket
from sqlalchemy import text

from app.database import async_session_factory

logger = logging.getLogger("clearledger.chat_ws")

_NOTIFY_CHANNEL = "clearledger_chat_ws"
_NOTIFY_MAX_BYTES = 7900
_RECONNECT_DELAY = 2


class ChatConnectionManager:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._socket_channels: dict[WebSocket, set[str]] = defaultdict(set)
        self._meta: dict[WebSocket, dict] = {}
        self._online: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._instance_id = str(uuid.uuid4())
        self._dsn: str | None = None
        self._listener: asyncpg.Connection | None = None
        self._listener_task: asyncio.Task | None = None
        self._listener_wakeup = asyncio.Event()
        self._delivery_tasks: set[asyncio.Task] = set()

    async def start(self, database_url: str) -> None:
        """Подключить общий PostgreSQL LISTEN/NOTIFY для всех Gunicorn workers."""
        if self._listener_task is not None:
            return
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            await self._connect_listener()
        except Exception as exc:  # noqa: BLE001 — локальная доставка остаётся доступна
            logger.error("Общий канал чата пока недоступен: %s", exc)
        self._listener_task = asyncio.create_task(self._monitor_listener())

    async def stop(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        listener = self._listener
        self._listener = None
        if listener is not None and not listener.is_closed():
            with suppress(Exception):
                await listener.remove_listener(_NOTIFY_CHANNEL, self._on_notification)
                await listener.close()
        pending = list(self._delivery_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _connect_listener(self) -> None:
        if not self._dsn:
            return
        old = self._listener
        if old is not None and not old.is_closed():
            with suppress(Exception):
                await old.close()
        listener = await asyncpg.connect(self._dsn)
        await listener.add_listener(_NOTIFY_CHANNEL, self._on_notification)
        listener.add_termination_listener(self._on_listener_terminated)
        self._listener = listener
        self._listener_wakeup.clear()
        logger.info("Общий канал WebSocket подключён")

    async def _monitor_listener(self) -> None:
        while True:
            listener = self._listener
            if listener is not None and not listener.is_closed():
                await self._listener_wakeup.wait()
                self._listener_wakeup.clear()
                continue
            try:
                await self._connect_listener()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — переподключение фонового канала
                logger.error("Переподключение общего канала чата не удалось: %s", exc)
                await asyncio.sleep(_RECONNECT_DELAY)

    def _on_listener_terminated(self, _connection: asyncpg.Connection) -> None:
        self._listener_wakeup.set()

    def _on_notification(
        self,
        _connection: asyncpg.Connection,
        _pid: int,
        _channel: str,
        raw: str,
    ) -> None:
        task = asyncio.create_task(self._deliver_notification(raw))
        self._delivery_tasks.add(task)
        task.add_done_callback(self._delivery_tasks.discard)

    def _notification_payload(self, channel: str, payload: dict) -> str:
        envelope = {"origin": self._instance_id, "channel": channel, "payload": payload}
        raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(raw.encode("utf-8")) <= _NOTIFY_MAX_BYTES:
            return raw
        compact_keys = (
            "type", "roomId", "messageId", "messageType", "userId", "userName",
            "pollId", "online", "fromName", "roomName",
        )
        compact = {key: payload[key] for key in compact_keys if key in payload}
        compact["truncated"] = True
        envelope["payload"] = compact
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=str)

    async def _publish(self, channel: str, payload: dict) -> None:
        raw = self._notification_payload(channel, payload)
        try:
            async with async_session_factory() as db:
                await db.execute(
                    text("SELECT pg_notify(:notify_channel, :payload)"),
                    {"notify_channel": _NOTIFY_CHANNEL, "payload": raw},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — локальные сокеты всё равно получили событие
            logger.error("Событие чата не попало в общий канал: %s", exc)

    async def _deliver_notification(self, raw: str) -> None:
        try:
            event = json.loads(raw)
            if event.get("origin") == self._instance_id:
                return
            channel = event["channel"]
            payload = event["payload"]
            if not isinstance(channel, str) or not isinstance(payload, dict):
                return
        except (KeyError, TypeError, ValueError):
            logger.warning("Получено некорректное событие общего канала чата")
            return
        await self._broadcast_local(channel, payload)

    async def connect(self, ws: WebSocket, user_id: str, company_id: str | None) -> bool:
        """Регистрирует сокет. Возвращает True, если юзер стал online (0→1)."""
        await ws.accept()
        async with self._lock:
            self._meta[ws] = {"user_id": user_id, "company_id": company_id}
            self._online[user_id] += 1
            became_online = self._online[user_id] == 1
        self.subscribe(ws, f"user:{user_id}")
        if company_id:
            self.subscribe(ws, f"company:{company_id}")
        return became_online

    async def disconnect(self, ws: WebSocket) -> tuple[str | None, str | None, bool]:
        """Снимает сокет. Возвращает (user_id, company_id, стал ли offline 1→0)."""
        async with self._lock:
            meta = self._meta.pop(ws, {})
            uid = meta.get("user_id")
            cid = meta.get("company_id")
            for channel in self._socket_channels.pop(ws, set()):
                self._channels[channel].discard(ws)
                if not self._channels[channel]:
                    self._channels.pop(channel, None)
            became_offline = False
            if uid:
                self._online[uid] -= 1
                if self._online[uid] <= 0:
                    self._online.pop(uid, None)
                    became_offline = True
        return uid, cid, became_offline

    def subscribe(self, ws: WebSocket, channel: str) -> None:
        self._channels[channel].add(ws)
        self._socket_channels[ws].add(channel)

    def unsubscribe(self, ws: WebSocket, channel: str) -> None:
        self._channels[channel].discard(ws)
        self._socket_channels[ws].discard(channel)

    def is_subscribed(self, ws: WebSocket, channel: str) -> bool:
        return channel in self._socket_channels.get(ws, set())

    def channels_of(self, ws: WebSocket) -> set[str]:
        return set(self._socket_channels.get(ws, set()))

    def online_user_ids(self) -> set[str]:
        return set(self._online.keys())

    def is_online(self, user_id: str) -> bool:
        return user_id in self._online

    async def _broadcast_local(
        self,
        channel: str,
        payload: dict,
        exclude: WebSocket | None = None,
    ) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._channels.get(channel, set())):
            if ws is exclude:
                continue
            try:
                await ws.send_json({**payload, "channel": channel})
            except Exception:  # noqa: BLE001 — мёртвый сокет
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    async def broadcast(self, channel: str, payload: dict, exclude: WebSocket | None = None) -> None:
        """Разослать событие локальным сокетам и сокетам остальных workers."""
        await self._broadcast_local(channel, payload, exclude)
        if self._dsn:
            await self._publish(channel, payload)


manager = ChatConnectionManager()
