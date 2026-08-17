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
_PRESENCE_TTL_SECONDS = 60
_PRESENCE_HEARTBEAT_SECONDS = 20


class ChatConnectionManager:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._socket_channels: dict[WebSocket, set[str]] = defaultdict(set)
        self._meta: dict[WebSocket, dict] = {}
        self._online: dict[str, int] = defaultdict(int)
        self._connection_ids: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()
        self._instance_id = str(uuid.uuid4())
        self._dsn: str | None = None
        self._listener: asyncpg.Connection | None = None
        self._listener_task: asyncio.Task | None = None
        self._listener_wakeup = asyncio.Event()
        self._delivery_tasks: set[asyncio.Task] = set()
        self._presence_ready = False
        self._presence_task: asyncio.Task | None = None

    async def start(self, database_url: str) -> None:
        """Подключить общий PostgreSQL LISTEN/NOTIFY для всех Gunicorn workers."""
        if self._listener_task is not None:
            return
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            await self._ensure_presence_table()
            self._presence_task = asyncio.create_task(self._heartbeat_presence())
        except Exception as exc:  # noqa: BLE001 — presence откатится к локальному счётчику
            logger.error("Общий presence чата пока недоступен: %s", exc)
        try:
            await self._connect_listener()
        except Exception as exc:  # noqa: BLE001 — локальная доставка остаётся доступна
            logger.error("Общий канал чата пока недоступен: %s", exc)
        self._listener_task = asyncio.create_task(self._monitor_listener())

    async def stop(self) -> None:
        presence_task = self._presence_task
        self._presence_task = None
        if presence_task is not None:
            presence_task.cancel()
            with suppress(asyncio.CancelledError):
                await presence_task
        if self._presence_ready:
            with suppress(Exception):
                async with async_session_factory() as db:
                    await db.execute(
                        text("DELETE FROM chat_ws_presence WHERE worker_id = :worker_id"),
                        {"worker_id": self._instance_id},
                    )
                    await db.commit()
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

    async def _ensure_presence_table(self) -> None:
        async with async_session_factory() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :key)"), {
                "namespace": 434_532,
                "key": 2,
            })
            await db.execute(text(
                "CREATE UNLOGGED TABLE IF NOT EXISTS chat_ws_presence ("
                " connection_id uuid PRIMARY KEY, worker_id uuid NOT NULL,"
                " user_id text NOT NULL, seen_at timestamptz NOT NULL DEFAULT now())"
            ))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chat_ws_presence_user_seen"
                " ON chat_ws_presence (user_id, seen_at)"
            ))
            await db.execute(text(
                "DELETE FROM chat_ws_presence"
                " WHERE seen_at < now() - make_interval(secs => :ttl)"
            ), {"ttl": _PRESENCE_TTL_SECONDS})
            await db.commit()
        self._presence_ready = True

    async def _heartbeat_presence(self) -> None:
        while True:
            await asyncio.sleep(_PRESENCE_HEARTBEAT_SECONDS)
            try:
                async with async_session_factory() as db:
                    await db.execute(text(
                        "UPDATE chat_ws_presence SET seen_at = now()"
                        " WHERE worker_id = :worker_id"
                    ), {"worker_id": self._instance_id})
                    await db.execute(text(
                        "DELETE FROM chat_ws_presence"
                        " WHERE seen_at < now() - make_interval(secs => :ttl)"
                    ), {"ttl": _PRESENCE_TTL_SECONDS})
                    await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — следующий heartbeat повторит
                logger.error("Heartbeat presence чата не записан: %s", exc)

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
        connection_id = str(uuid.uuid4())
        async with self._lock:
            self._meta[ws] = {"user_id": user_id, "company_id": company_id}
            self._connection_ids[ws] = connection_id
            self._online[user_id] += 1
            became_online = self._online[user_id] == 1
        self.subscribe(ws, f"user:{user_id}")
        if company_id:
            self.subscribe(ws, f"company:{company_id}")
        if self._presence_ready:
            try:
                async with async_session_factory() as db:
                    await db.execute(text(
                        "INSERT INTO chat_ws_presence"
                        " (connection_id, worker_id, user_id, seen_at)"
                        " VALUES (:connection_id, :worker_id, :user_id, now())"
                    ), {
                        "connection_id": connection_id,
                        "worker_id": self._instance_id,
                        "user_id": user_id,
                    })
                    count = await db.scalar(text(
                        "SELECT count(*) FROM chat_ws_presence"
                        " WHERE user_id = :user_id"
                        " AND seen_at >= now() - make_interval(secs => :ttl)"
                    ), {"user_id": user_id, "ttl": _PRESENCE_TTL_SECONDS})
                    await db.commit()
                became_online = int(count or 0) == 1
            except Exception as exc:  # noqa: BLE001 — локальный presence остаётся
                logger.error("Presence подключения не записан: %s", exc)
        return became_online

    async def disconnect(self, ws: WebSocket) -> tuple[str | None, str | None, bool]:
        """Снимает сокет. Возвращает (user_id, company_id, стал ли offline 1→0)."""
        async with self._lock:
            meta = self._meta.pop(ws, {})
            connection_id = self._connection_ids.pop(ws, None)
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
        if self._presence_ready and connection_id and uid:
            try:
                async with async_session_factory() as db:
                    await db.execute(text(
                        "DELETE FROM chat_ws_presence WHERE connection_id = :connection_id"
                    ), {"connection_id": connection_id})
                    remains = await db.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM chat_ws_presence"
                        " WHERE user_id = :user_id"
                        " AND seen_at >= now() - make_interval(secs => :ttl))"
                    ), {"user_id": uid, "ttl": _PRESENCE_TTL_SECONDS})
                    await db.commit()
                became_offline = not bool(remains)
            except Exception as exc:  # noqa: BLE001 — локальный результат остаётся
                logger.error("Presence отключения не удалён: %s", exc)
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

    async def online_user_ids(self) -> set[str]:
        if self._presence_ready:
            try:
                async with async_session_factory() as db:
                    rows = await db.scalars(text(
                        "SELECT DISTINCT user_id FROM chat_ws_presence"
                        " WHERE seen_at >= now() - make_interval(secs => :ttl)"
                    ), {"ttl": _PRESENCE_TTL_SECONDS})
                    return set(rows) | set(self._online.keys())
            except Exception as exc:  # noqa: BLE001 — локальный счётчик остаётся
                logger.error("Общий presence не прочитан: %s", exc)
        return set(self._online.keys())

    async def is_online(self, user_id: str) -> bool:
        return user_id in await self.online_user_ids()

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
