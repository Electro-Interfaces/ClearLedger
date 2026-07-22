"""Низкоуровневый клиент Synapse Admin/Client API (модель провижининга «как в Ангаре»).

Все операции — от имени сервисного admin-аккаунта (`@<prefix>-svc`, PL100 создатель комнат)
по ВНУТРЕННЕМУ адресу Synapse. Admin-токен НИКОГДА не уходит на фронт. Провижининг
пользователей — через Admin API (не shared-secret): создать/обновить пользователя со
случайным паролем + залогинить его admin-эндпоинтом, чтобы выдать per-user токен.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import secrets
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

settings = get_settings()

_LOCALPART_RE = re.compile(r"[^a-z0-9._=/-]")


def server_name() -> str:
    return settings.matrix_server_name or ""


def public_homeserver() -> str:
    return settings.matrix_homeserver_public or ""


def mxid_for(user_id) -> str:
    """Стабильный mxid по id пользователя Ledger: @<prefix>_<uuidhex>:<server>.
    Привязка фиксируется в MatrixIdentity навсегда (не зависит от смены имени)."""
    token = _LOCALPART_RE.sub("", str(user_id).lower().replace("-", ""))
    return f"@{settings.matrix_mxid_prefix}_{token}:{server_name()}"


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.matrix_admin_token}", "Content-Type": "application/json"}


async def _mreq(method: str, path: str, json: Any = None, *, retries: int = 4) -> Any:
    """HTTP к Synapse с backoff на 429 (уважает retry_after_ms). Возвращает JSON."""
    url = settings.synapse_url.rstrip("/") + path
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(retries + 1):
            try:
                r = await client.request(method, url, headers=_admin_headers(), json=json)
                if r.status_code == 429 and attempt < retries:
                    body = {}
                    try:
                        body = r.json()
                    except Exception:  # noqa: BLE001
                        pass
                    wait_ms = int(body.get("retry_after_ms", 1000))
                    await asyncio.sleep(min(wait_ms, 5000) / 1000)
                    continue
                r.raise_for_status()
                return r.json() if r.content else {}
            except httpx.HTTPStatusError as e:  # noqa: PERF203
                last = e
                if e.response is not None and e.response.status_code < 500:
                    raise
                await asyncio.sleep(0.4 * (attempt + 1))
            except httpx.HTTPError as e:
                last = e
                await asyncio.sleep(0.4 * (attempt + 1))
    if last:
        raise last
    raise RuntimeError("matrix admin request failed")


# ── провижининг пользователей ──

async def admin_upsert_user(mxid: str, displayname: str | None) -> None:
    """Создать/обновить Matrix-пользователя (случайный пароль). Идемпотентно."""
    pw = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode().rstrip("=")
    await _mreq("PUT", f"/_synapse/admin/v2/users/{quote(mxid, safe='')}",
                {"password": pw, "admin": False, "deactivated": False,
                 **({"displayname": displayname} if displayname else {})})


async def get_user_login_token(mxid: str) -> str:
    """Выдать per-user access_token без пароля (admin login). В БД не храним."""
    d = await _mreq("POST", f"/_synapse/admin/v1/users/{quote(mxid, safe='')}/login", {})
    return d["access_token"]


# ── комнаты (client API от имени сервисного аккаунта) ──

async def create_room(*, name: str | None = None, topic: str | None = None,
                      is_direct: bool = False, is_public: bool = False) -> str:
    body: dict[str, Any] = {
        "preset": "public_chat" if is_public else "private_chat",
        "visibility": "public" if is_public else "private",
        "is_direct": is_direct,
    }
    if name:
        body["name"] = name
    if topic:
        body["topic"] = topic
    d = await _mreq("POST", "/_matrix/client/v3/createRoom", body)
    return d["room_id"]


async def force_join(room_id: str, mxid: str) -> None:
    """Ввести пользователя в комнату admin-ом (щадит rate-limit паузой)."""
    await _mreq("POST", f"/_synapse/admin/v1/join/{quote(room_id, safe='')}", {"user_id": mxid})
    await asyncio.sleep(0.6)


async def kick(room_id: str, mxid: str, reason: str = "") -> None:
    await _mreq("POST", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/kick",
                {"user_id": mxid, "reason": reason})


async def set_room_name(room_id: str, name: str) -> None:
    await _mreq("PUT", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/state/m.room.name/",
                {"name": name})


async def set_join_rules(room_id: str, is_public: bool) -> None:
    await _mreq("PUT", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/state/m.room.join_rules/",
                {"join_rule": "public" if is_public else "invite"})


async def set_directory_visibility(room_id: str, is_public: bool) -> None:
    await _mreq("PUT", f"/_matrix/client/v3/directory/list/room/{quote(room_id, safe='')}",
                {"visibility": "public" if is_public else "private"})


async def _power_levels(room_id: str) -> dict[str, Any]:
    return await _mreq("GET", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/state/m.room.power_levels/")


async def set_user_power(room_id: str, mxid: str, power: int) -> None:
    """Read-modify-write m.room.power_levels: роль участника (100 владелец/50 админ/0 участник)."""
    pl = await _power_levels(room_id)
    users = dict(pl.get("users") or {})
    users[mxid] = power
    pl["users"] = users
    await _mreq("PUT", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/state/m.room.power_levels/", pl)


async def get_user_power(room_id: str, mxid: str) -> int:
    pl = await _power_levels(room_id)
    users = pl.get("users") or {}
    return int(users.get(mxid, pl.get("users_default", 0)))


async def get_joined_members(room_id: str) -> list[str]:
    d = await _mreq("GET", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/joined_members")
    return list((d.get("joined") or {}).keys())


async def server_version() -> dict[str, Any]:
    return await _mreq("GET", "/_synapse/admin/v1/server_version")
