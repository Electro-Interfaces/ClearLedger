"""
In-memory менеджер WebSocket-соединений чата (порт ws-manager из TSupport).

Каналы вида "kind:id": user:{uid}, company:{cid}, chat:{room_id}.
Presence — счётчик активных сокетов на пользователя (несколько вкладок = корректно).
Одна реплика бэкенда (in-memory); при горизонтальном масштабировании нужен Redis pub/sub.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ChatConnectionManager:
    def __init__(self) -> None:
        # channel -> набор сокетов, подписанных на него
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        # сокет -> его каналы (для отписки при disconnect)
        self._socket_channels: dict[WebSocket, set[str]] = defaultdict(set)
        # сокет -> user_id/company_id (метаданные)
        self._meta: dict[WebSocket, dict] = {}
        # user_id -> число активных сокетов (presence)
        self._online: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user_id: str, company_id: str | None) -> bool:
        """Регистрирует сокет. Возвращает True, если юзер стал online (0→1)."""
        await ws.accept()
        async with self._lock:
            self._meta[ws] = {"user_id": user_id, "company_id": company_id}
            self._online[user_id] += 1
            became_online = self._online[user_id] == 1
        # авто-подписка на личный и компанийный каналы
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
            for ch in self._socket_channels.pop(ws, set()):
                self._channels[ch].discard(ws)
                if not self._channels[ch]:
                    self._channels.pop(ch, None)
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

    async def broadcast(self, channel: str, payload: dict, exclude: WebSocket | None = None) -> None:
        """Разослать payload всем подписчикам канала (кроме exclude)."""
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


# Единый экземпляр на процесс.
manager = ChatConnectionManager()
