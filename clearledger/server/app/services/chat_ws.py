"""WebSocket-соединения чата и межпроцессная доставка через PostgreSQL."""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import asyncpg
from fastapi import WebSocket
from sqlalchemy import text

from app.database import async_session_factory
from app.services import chat_ws_session as sessions

logger = logging.getLogger("clearledger.chat_ws")

_NOTIFY_CHANNEL = "clearledger_chat_ws"
_NOTIFY_MAX_BYTES = 7900
_RECONNECT_DELAY = 2
_PRESENCE_TTL_SECONDS = 60
_PRESENCE_HEARTBEAT_SECONDS = 20


@dataclass
class _SocketSession:
    identity: sessions.NativeWsSession
    proof: sessions.NativeWsProof
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False
    accepted: bool = False
    peer_terminal: bool = False
    epoch: int = 0
    watchdog: asyncio.Task | None = None
    deadline: asyncio.Task | None = None
    check: asyncio.Task | None = None
    check_channel: str | None = None
    cleanup: asyncio.Task | None = None
    payload_checks: set[asyncio.Task] = field(default_factory=set)



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
        self._listener_lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None
        self._listener_wakeup = asyncio.Event()
        self._delivery_tasks: set[asyncio.Task] = set()
        self._presence_ready = False
        self._presence_task: asyncio.Task | None = None
        self._sessions: dict[WebSocket, _SocketSession] = {}
        self._closing: dict[WebSocket, asyncio.Task] = {}
        self._owned_tasks: set[asyncio.Task] = set()
        self._stopping = False
        self._drain_failed = False
        self._startup_task: asyncio.Task | None = None
        self._stop_count = 0
        self._generation = 0

    @asynccontextmanager
    async def _database(self):
        """Every manager DB owner retains unproven public-session cleanup."""
        try:
            async with sessions.managed_db(async_session_factory) as db:
                yield db
        except sessions.DbCleanupFailed:
            self._drain_failed = True
            raise

    async def start(self, database_url: str) -> None:
        """Подключить общий PostgreSQL LISTEN/NOTIFY для всех Gunicorn workers."""
        if self._drain_failed:
            raise RuntimeError("Previous chat cleanup failed")
        if self._stop_count:
            raise RuntimeError("Chat shutdown in progress")
        if self._listener_task is not None:
            return
        task = self._startup_task
        if task is None:
            self._stopping = False
            task = self._track(asyncio.create_task(self._start(database_url, self._generation),
                               name="chat-ws-startup", context=contextvars.Context()))
            self._startup_task = task
            def clear(completed):
                if self._startup_task is completed:
                    self._startup_task = None
            task.add_done_callback(clear)
        await self._await_owned(task)

    async def _await_owned(self, task):
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done() and not task.cancelling():
                task.cancel()
            results = await asyncio.gather(task, return_exceptions=True)
            error = results[0]
            if isinstance(error, BaseException) and not isinstance(error, asyncio.CancelledError):
                raise error
            raise

    def _assert_startup_generation(self, generation):
        if self._drain_failed:
            raise RuntimeError("Previous chat cleanup failed")
        if self._stopping or generation != self._generation:
            raise asyncio.CancelledError()

    async def _start(self, database_url, generation):
        presence = None
        try:
            self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
            try:
                await self._ensure_presence_table()
                self._assert_startup_generation(generation)
                self._presence_task = self._track(asyncio.create_task(self._heartbeat_presence()))
                presence = self._presence_task
            except sessions.DbCleanupFailed:
                raise
            except Exception as exc:  # noqa: BLE001 — presence откатится к локальному счётчику
                if self._drain_failed:
                    raise
                logger.error("Общий presence чата пока недоступен: %s", exc)
            self._assert_startup_generation(generation)
            try:
                await self._connect_listener()
            except Exception as exc:  # noqa: BLE001 — локальная доставка остаётся доступна
                if self._drain_failed:
                    raise
                logger.error("Общий канал чата пока недоступен: %s", exc)
            self._assert_startup_generation(generation)
            self._listener_task = self._track(asyncio.create_task(self._monitor_listener()))
        except BaseException:
            # Startup owns children created before listener setup, too. A clean
            # cancellation cannot leave a heartbeat or late monitor behind.
            if presence is not None:
                if not presence.done() and not presence.cancelling():
                    presence.cancel()
                results = await asyncio.gather(presence, return_exceptions=True)
                if any(isinstance(error, sessions.DbCleanupFailed) for error in results):
                    self._drain_failed = True
                if self._presence_task is presence:
                    self._presence_task = None
            listener = self._listener
            if not self._drain_failed and listener is not None and not listener.is_closed():
                await self._close_listener(listener)
            raise

    async def stop(self) -> None:
        self._stop_count += 1
        self._stopping = True
        self._generation += 1
        try:
            await self._stop()
        finally:
            self._stop_count -= 1

    async def _stop(self):
        self._stopping = True
        # Invalidate before any await; no queued send may revive a stopped socket.
        cleanups = list({*(self._begin_close(ws, 1001, "server_shutdown") for ws in list(self._sessions)),
                         *self._closing.values(),
                         *(t for t in self._owned_tasks if t.get_name() == "chat-ws-cleanup")})
        for task in (self._presence_task, self._listener_task, *self._delivery_tasks):
            if task is not None:
                task.cancel()
        try:
            async with asyncio.timeout(sessions.DRAIN_TIMEOUT):
                results = await asyncio.gather(*cleanups, return_exceptions=True)
                if any(isinstance(r, BaseException) for r in results):
                    self._drain_failed = True
                pending = [t for t in (*self._owned_tasks, *self._delivery_tasks,
                                       self._presence_task, self._listener_task) if t is not None]
                for task in pending:
                    if not task.cancelling():
                        task.cancel()
                results = await asyncio.gather(*pending, return_exceptions=True)
                if any(isinstance(r, BaseException)
                       and not isinstance(r, (asyncio.CancelledError, sessions.SessionDenied))
                       or isinstance(r, sessions.SessionDenied) and r.cleanup_failed for r in results):
                    self._drain_failed = True
                listener = self._listener
                if listener is not None and not listener.is_closed():
                    try:
                        await listener.remove_listener(_NOTIFY_CHANNEL, self._on_notification)
                    finally:
                        await self._close_listener(listener)
                self._listener = None
                if self._presence_ready:
                    async with self._database() as db:
                        await db.execute(text("DELETE FROM chat_ws_presence WHERE worker_id = :worker_id"),
                                         {"worker_id": self._instance_id})
                        await db.commit()
        finally:
            self._presence_task = self._listener_task = None
            # Remaining uncooperative tasks remain tracked: never certify a drain.
            remaining = [t for t in (*self._owned_tasks, *self._delivery_tasks) if not t.done()]
            for task in remaining:
                if not task.cancelling():
                    task.cancel()
            if remaining:
                self._drain_failed = True
                raise RuntimeError("Chat task drain incomplete")
            if self._drain_failed:
                raise RuntimeError("Chat lifecycle cleanup failed")

    async def _ensure_presence_table(self) -> None:
        async with self._database() as db:
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
                async with self._database() as db:
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
            except sessions.DbCleanupFailed:
                raise
            except Exception as exc:  # noqa: BLE001 — следующий heartbeat повторит
                if isinstance(exc, sessions.DbCleanupFailed):
                    self._drain_failed = True
                logger.error("Heartbeat presence чата не записан: %s", exc)

    async def _connect_listener(self) -> None:
        if not self._dsn:
            return
        task = self._track(asyncio.create_task(self._acquire_listener(),
                           name="chat-ws-listener-setup", context=contextvars.Context()))
        await self._await_owned(task)

    async def _close_listener(self, listener):
        try:
            async with asyncio.timeout(sessions.DRAIN_TIMEOUT):
                await listener.close()
            if not listener.is_closed():
                raise RuntimeError("Chat listener close incomplete")
        except BaseException:
            self._drain_failed = True
            raise
        if self._listener is listener:
            self._listener = None

    async def _acquire_listener(self):
        # This lock belongs only to the listener resource, never the socket map.
        async with self._listener_lock:
            generation = self._generation
            self._assert_startup_generation(generation)
            old = self._listener
            if old is not None:
                if not old.is_closed():
                    await self._close_listener(old)
                else:
                    self._listener = None
            self._assert_startup_generation(generation)
            listener = await asyncpg.connect(self._dsn)
            self._listener = listener  # ownership precedes every awaited setup step
            try:
                self._assert_startup_generation(generation)
                await listener.add_listener(_NOTIFY_CHANNEL, self._on_notification)
                self._assert_startup_generation(generation)
                listener.add_termination_listener(self._on_listener_terminated)
                self._listener_wakeup.clear()
                logger.info("Общий канал WebSocket подключён")
            except BaseException:
                await self._close_listener(listener)
                raise

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
        if self._stopping:
            return
        task = asyncio.create_task(self._deliver_notification(raw), context=contextvars.Context())
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
            async with self._database() as db:
                await db.execute(
                    text("SELECT pg_notify(:notify_channel, :payload)"),
                    {"notify_channel": _NOTIFY_CHANNEL, "payload": raw},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — локальные сокеты всё равно получили событие
            if isinstance(exc, sessions.DbCleanupFailed):
                self._drain_failed = True
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

    async def _close_preaccept(self, ws, code, reason):
        try:
            async with asyncio.timeout(sessions.SEND_TIMEOUT):
                await ws.close(code=code, reason=reason)
        except BaseException:
            self._drain_failed = True
            raise

    async def reject(self, ws, code, reason):
        """Malformed/duplicate handshake denial is also a tracked lifecycle task."""
        task = self._track(asyncio.create_task(self._close_preaccept(ws, code, reason),
                            name="chat-ws-cleanup", context=contextvars.Context()))
        await asyncio.shield(task)

    async def _admit(self, payload, selector, ws):
        try:
            identity, proof = await sessions.open_session(payload, selector)
            if self._stopping or self._drain_failed:
                raise sessions.SessionDenied("temporarily_unavailable", 1013)
            return identity, proof
        except BaseException as exc:
            if isinstance(exc, sessions.SessionDenied) and exc.cleanup_failed:
                self._drain_failed = True
            if ws is not None:
                if self._stopping:
                    code, reason = 1001, "server_shutdown"
                elif isinstance(exc, sessions.SessionDenied):
                    code, reason = exc.code, exc.reason
                elif isinstance(exc, asyncio.CancelledError):
                    code, reason = 1001, "server_shutdown"
                else:
                    code, reason = 1013, "temporarily_unavailable"
                await self._close_preaccept(ws, code, reason)
            raise

    async def admit(self, payload, selector=None, *, ws=None):
        """Own admission before its first await, even with no registered socket."""
        if self._stopping or self._drain_failed:
            if ws is not None:
                await self.reject(ws, 1001 if self._stopping else 1013,
                                  "server_shutdown" if self._stopping else "temporarily_unavailable")
            raise sessions.SessionDenied("temporarily_unavailable", 1013)
        task = self._track(asyncio.create_task(self._admit(payload, selector, ws),
                           name="chat-ws-admission", context=contextvars.Context()))
        return await task

    async def connect(self, ws: WebSocket, user_id: str, company_id: str | None, *,
                      session: sessions.NativeWsSession, proof: sessions.NativeWsProof) -> bool:
        session.require_live()
        if self._stopping:
            await self.reject(ws, 1001, "server_shutdown")
            raise sessions.SessionDenied("temporarily_unavailable", 1013)
        if (user_id != str(session.user_id) or proof.user_id != session.user_id
                or company_id != (str(session.company_id) if session.company_id else None)
                or proof.company_id != session.company_id):
            raise sessions.SessionDenied()
        state = _SocketSession(session, proof)
        self._sessions[ws] = state
        try:
            async with state.lock:
                async with asyncio.timeout(sessions.SEND_TIMEOUT):
                    await ws.accept()
                state.accepted = True
                session.require_live()
                if state.closed or self._stopping:
                    raise sessions.SessionDenied("temporarily_unavailable", 1013)
                connection_id = str(uuid.uuid4())
                async with self._lock:
                    self._meta[ws] = {"user_id": user_id, "company_id": company_id}
                    self._connection_ids[ws] = connection_id
                    self._online[user_id] += 1
                    became_online = self._online[user_id] == 1
                self.subscribe(ws, f"user:{user_id}")
                if company_id:
                    self.subscribe(ws, f"company:{company_id}")
                budget = min(sessions.CHECK_TIMEOUT, max(0.001, session.monotonic_expiry - sessions.monotonic()))
                async with asyncio.timeout(budget):
                    became_online = await self._connect_presence(user_id, connection_id, became_online)
                session.require_live()
            if state.closed or self._stopping:
                raise sessions.SessionDenied("temporarily_unavailable", 1013)
            state.watchdog = self._track(asyncio.create_task(self._watch(ws, state),
                                                            context=contextvars.Context()))
            state.deadline = self._track(asyncio.create_task(self._deadline(ws, state),
                                                            context=contextvars.Context()))
            return became_online
        except BaseException as exc:
            try:
                session.require_live()
            except sessions.SessionDenied as expired:
                exc = expired
            if isinstance(exc, sessions.SessionDenied):
                await self.close(ws, exc.code, exc.reason)
            else:
                await self.close(ws, 1001 if isinstance(exc, asyncio.CancelledError) else 1013,
                                 "server_shutdown" if isinstance(exc, asyncio.CancelledError) else "temporarily_unavailable")
            raise

    async def _connect_presence(self, user_id, connection_id, became_online):
        if self._presence_ready:
            try:
                async with self._database() as db:
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
                if isinstance(exc, sessions.DbCleanupFailed):
                    self._drain_failed = True
                    raise
                logger.error("Presence подключения не записан: %s", exc)
        return became_online

    def _detach_local(self, ws):
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
        return uid, cid, connection_id, became_offline

    async def disconnect(self, ws: WebSocket) -> tuple[str | None, str | None, bool]:
        """Снимает сокет. Возвращает (user_id, company_id, стал ли offline 1→0)."""
        state = self._sessions.pop(ws, None)
        children = []
        if state is not None:
            state.closed = True
            state.epoch += 1
            children = [t for t in (state.check, state.watchdog, state.deadline, *state.payload_checks)
                        if t is not None and t is not asyncio.current_task()]
            for task in children:
                task.cancel()
        async with self._lock:
            uid, cid, connection_id, became_offline = self._detach_local(ws)
        if children:
            async with asyncio.timeout(sessions.DRAIN_TIMEOUT):
                await asyncio.gather(*children, return_exceptions=True)
        if self._presence_ready and connection_id and uid:
            try:
                async with self._database() as db:
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
                if isinstance(exc, sessions.DbCleanupFailed):
                    self._drain_failed = True
                    raise
                logger.error("Presence отключения не удалён: %s", exc)
        return uid, cid, became_offline

    def subscribe(self, ws: WebSocket, channel: str) -> None:
        state = self._sessions.get(ws)
        if state is None or state.closed or not state.accepted:
            raise sessions.SessionDenied()
        if channel not in self._socket_channels.get(ws, set()):
            state.epoch += 1
        self._channels[channel].add(ws)
        self._socket_channels[ws].add(channel)

    def unsubscribe(self, ws: WebSocket, channel: str) -> None:
        state = self._sessions.get(ws)
        if state is not None and self.is_subscribed(ws, channel):
            state.epoch += 1
        subscribers = self._channels.get(channel)
        if subscribers is not None:
            subscribers.discard(ws)
            if not subscribers:
                self._channels.pop(channel, None)
        self._socket_channels.get(ws, set()).discard(channel)

    def is_subscribed(self, ws: WebSocket, channel: str) -> bool:
        return channel in self._socket_channels.get(ws, set())

    def channels_of(self, ws: WebSocket) -> set[str]:
        return set(self._socket_channels.get(ws, set()))

    async def online_user_ids(self) -> set[str]:
        if self._presence_ready:
            try:
                async with self._database() as db:
                    rows = await db.scalars(text(
                        "SELECT DISTINCT user_id FROM chat_ws_presence"
                        " WHERE seen_at >= now() - make_interval(secs => :ttl)"
                    ), {"ttl": _PRESENCE_TTL_SECONDS})
                    return set(rows) | set(self._online.keys())
            except sessions.DbCleanupFailed:
                raise
            except Exception as exc:  # noqa: BLE001 — локальный счётчик остаётся
                logger.error("Общий presence не прочитан: %s", exc)
        return set(self._online.keys())

    async def is_online(self, user_id: str) -> bool:
        return user_id in await self.online_user_ids()

    async def _broadcast_local(self, channel: str, payload: dict,
                               exclude: WebSocket | None = None,
                               actor: WebSocket | None = None) -> None:
        for ws in list(self._channels.get(channel, set())):
            if ws is exclude or self._stopping:
                continue
            if actor is not None and not self.is_live(actor):
                return
            await self.send(ws, {**payload, "channel": channel}, channel=channel, actor=actor)

    async def broadcast(self, channel: str, payload: dict, exclude: WebSocket | None = None,
                        *, actor: WebSocket | None = None) -> None:
        await self._broadcast_local(channel, payload, exclude, actor)
        if self._dsn and not self._stopping and (actor is None or self.is_live(actor)):
            await self._publish(channel, payload)

    def _track(self, task, *, ws=None):
        self._owned_tasks.add(task)
        def done(completed):
            self._owned_tasks.discard(completed)
            if completed.cancelled():
                if completed.get_name() == "chat-ws-cleanup":
                    self._drain_failed = True
            else:
                error = completed.exception()  # retrieve even if every waiter was cancelled
                if (completed.get_name() == "chat-ws-cleanup" and error is not None
                        or completed.get_name() == "chat-ws-admission" and error is not None
                        and not isinstance(error, sessions.SessionDenied)
                        or isinstance(error, sessions.DbCleanupFailed)
                        or isinstance(error, sessions.SessionDenied) and error.cleanup_failed):
                    self._drain_failed = True
                if ws is not None and error is not None:
                    if isinstance(error, sessions.SessionDenied):
                        self._begin_close(ws, error.code, error.reason)
                    else:
                        self._begin_close(ws, 1013, "temporarily_unavailable")
        task.add_done_callback(done)
        return task

    def is_live(self, ws: WebSocket) -> bool:
        state = self._sessions.get(ws)
        if state is None or state.closed or self._stopping or self._drain_failed:
            return False
        try:
            state.identity.require_live()
            return sessions.monotonic() - state.proof.checked_at < sessions.CHECK_CADENCE
        except sessions.SessionDenied:
            return False

    async def _refresh(self, ws, *, force=False, channel=None, checker=None):
        state = self._sessions.get(ws)
        if state is None or state.closed:
            raise sessions.SessionDenied()
        while True:
            if self._drain_failed:
                raise sessions.SessionDenied("temporarily_unavailable", 1013)
            state.identity.require_live()
            wanted = self.channels_of(ws) | ({channel} if channel is not None else set())
            due = sessions.monotonic() - state.proof.checked_at >= sessions.CHECK_CADENCE
            if not force and not due and wanted <= state.proof.allowed:
                return state.proof
            task = state.check
            own_explicit = False
            if task is None:
                task = sessions.start_check(state.identity, wanted,
                    explicit_channel=channel if force else None, checker=checker if force else None)
                state.check, state.check_channel = self._track(task, ws=ws), channel if force else None
                own_explicit = force
            else:
                own_explicit = force and state.check_channel == channel and channel is not None
            epoch = state.epoch
            try:
                proof = await asyncio.shield(task)
            except sessions.SessionDenied as exc:
                if exc.cleanup_failed:
                    self._drain_failed = True
                raise
            finally:
                if task.done() and state.check is task:
                    state.check, state.check_channel = None, None
            state.identity.require_live()
            if state.closed or self._sessions.get(ws) is not state:
                raise sessions.SessionDenied()
            if epoch != state.epoch:
                continue
            state.proof = proof
            denied = self.channels_of(ws) - proof.allowed
            for denied_channel in denied:
                self.unsubscribe(ws, denied_channel)
            if force and not own_explicit:
                continue
            return proof

    async def current(self, ws):
        try:
            return await self._refresh(ws)
        except sessions.SessionDenied:
            raise
        except Exception:
            raise sessions.SessionDenied("temporarily_unavailable", 1013) from None

    async def subscribe_current(self, ws, channel, checker):
        if not isinstance(channel, str):
            raise TypeError("channel must be a string")
        try:
            proof = await self._refresh(ws, force=True, channel=channel, checker=checker)
            if channel in proof.allowed:
                self.subscribe(ws, channel)
                return True
            await self.send(ws, {"type": "subscribe:denied", "channel": channel})
            return False
        except sessions.SessionDenied as exc:
            await self.close(ws, exc.code, exc.reason)
            return False

    async def typing_current(self, ws, channel, checker):
        if not self.is_subscribed(ws, channel):
            return
        try:
            proof = await self._refresh(ws, force=True, channel=channel, checker=checker)
            if channel not in proof.allowed:
                self.unsubscribe(ws, channel)
                return
            if self.is_live(ws):
                await self.broadcast(channel, {"type": "chat:typing", "userId": str(proof.user_id),
                    "userName": proof.user_name}, exclude=ws, actor=ws)
        except sessions.SessionDenied as exc:
            await self.close(ws, exc.code, exc.reason)

    async def _frame(self, ws, state, payload, channel=None, actor=None, epoch=None):
        async with asyncio.timeout(sessions.SEND_TIMEOUT):
            async with state.lock:
                state.identity.require_live()
                if self._drain_failed:
                    raise sessions.SessionDenied("temporarily_unavailable", 1013)
                if sessions.monotonic() - state.proof.checked_at >= sessions.CHECK_CADENCE:
                    raise sessions.SessionDenied("temporarily_unavailable", 1013)
                if (state.closed or self._sessions.get(ws) is not state or self._stopping
                        or epoch is not None and state.epoch != epoch
                        or channel is not None and not self.is_subscribed(ws, channel)
                        or actor is not None and not self.is_live(actor)):
                    return False
                await ws.send_json(payload)
                state.identity.require_live()
                return not state.closed

    async def send(self, ws, payload, *, channel=None, actor=None):
        state = self._sessions.get(ws)
        if state is None or state.closed:
            return False
        try:
            await self._refresh(ws)
            epoch = state.epoch
            if (channel is not None or payload.get("roomId") is not None
                    or str(payload.get("type", "")).startswith("chat:")):
                check = sessions.start_delivery(state.identity, channel or "", payload)
                if isinstance(check, asyncio.Task):
                    self._track(check, ws=ws)
                    state.payload_checks.add(check)
                    check.add_done_callback(state.payload_checks.discard)
                    try:
                        allowed = await asyncio.shield(check)
                    except asyncio.CancelledError:
                        if not check.done() and not check.cancelling():
                            check.cancel()
                        raise
                else:
                    allowed = check
                state.identity.require_live()
                if not allowed or channel is not None and channel not in state.proof.allowed:
                    return False
            return await self._frame(ws, state, payload, channel, actor, epoch)
        except sessions.SessionDenied as exc:
            await self.close(ws, exc.code, exc.reason)
        except Exception:
            await self.close(ws, 1013, "temporarily_unavailable")
        return False

    async def _deadline(self, ws, state):
        # This task never awaits an authority query: a slow proof cannot delay expiry.
        try:
            while not state.closed:
                await asyncio.sleep(min(state.identity.expiry_delay(), sessions.CHECK_CADENCE))
                state.identity.require_live()
        except sessions.SessionDenied as exc:
            await self.close(ws, exc.code, exc.reason)

    async def _watch(self, ws, state):
        try:
            while not state.closed:
                await asyncio.sleep(state.identity.next_delay(state.proof.checked_at))
                await self._refresh(ws)
        except sessions.SessionDenied as exc:
            await self.close(ws, exc.code, exc.reason)
        except Exception:
            await self.close(ws, 1013, "temporarily_unavailable")

    def _begin_close(self, ws, code, reason):
        pending = self._closing.get(ws)
        if pending is not None:
            return pending
        state = self._sessions.get(ws)
        if state is None:
            task = asyncio.create_task(asyncio.sleep(0), context=contextvars.Context())
            return self._track(task)
        if state.cleanup is not None:
            return state.cleanup
        state.closed = True
        state.epoch += 1
        state.cleanup = self._track(asyncio.create_task(self._finish(ws, state, code, reason),
                                                       name="chat-ws-cleanup", context=contextvars.Context()))
        self._closing[ws] = state.cleanup
        def finished(completed):
            if self._closing.get(ws) is completed:
                self._closing.pop(ws)
        state.cleanup.add_done_callback(finished)
        return state.cleanup

    async def close(self, ws, code=1000, reason=""):
        await asyncio.shield(self._begin_close(ws, code, reason))

    def peer_disconnected(self, ws):
        """Only the router's received WebSocketDisconnect establishes this fact."""
        state = self._sessions.get(ws)
        if state is not None:
            state.peer_terminal = True
            state.closed = True
            state.epoch += 1

    async def _finish(self, ws, state, code, reason):
        children = [t for t in (state.check, state.watchdog, state.deadline, *state.payload_checks) if t is not None]
        try:
            async with asyncio.timeout(sessions.DRAIN_TIMEOUT):
                # Registration/presence and close share this per-socket lock;
                # no late INSERT can follow the DELETE. Never the global map lock.
                async with state.lock:
                    close_error = None
                    try:
                        if state.accepted and not state.peer_terminal:
                            await ws.close(code=code, reason=reason)
                    except BaseException as exc:
                        self._drain_failed = True
                        close_error = exc
                    finally:
                        # A real close failure is retained, but never skips the
                        # presence DELETE or cancellation/reaping of owned checks.
                        async with asyncio.timeout(sessions.DRAIN_TIMEOUT):
                            uid, cid, offline = await self.disconnect(ws)
                            await asyncio.gather(*children, return_exceptions=True)
                if offline and cid:
                    async with self._database() as db:
                        await db.execute(text("UPDATE users SET last_seen_at = now() WHERE id = :u"), {"u": uuid.UUID(uid)})
                        await db.commit()
                    if not self._stopping:
                        await self.broadcast(f"company:{cid}", {"type": "presence", "userId": uid, "online": False})
                if close_error is not None:
                    raise close_error
        finally:
            self._sessions.pop(ws, None)
            self._detach_local(ws)
            # A failed ASGI close can precede disconnect's cancellation owner.
            # Leave resource cleanup tracked, and never report that failure as
            # a successful drain. Do not inject a second cancellation into DB close.
            remaining = [t for t in children if not t.done()]
            for task in remaining:
                if not task.cancelling():
                    task.cancel()
            if remaining:
                self._drain_failed = True



manager = ChatConnectionManager()
