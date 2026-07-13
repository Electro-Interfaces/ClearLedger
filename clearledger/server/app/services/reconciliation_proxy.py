"""
Прокси к внешним API TradeCorp и MSTO для модуля «Сверки» (корп-карты + онлайн-заказы).

Перенесён из TradeFrame (server/routes/tradecorp.js, server/routes/msto.js,
server/services/mstoProxyService.js). Секреты TradeCorp/MSTO остаются на сервере (httpx),
фронт ходит только в /api/tradecorp/* и /api/msto/*.

Токены кэшируются в памяти процесса: TradeCorp ~55 мин, MSTO ~23 ч. GET-ответы MSTO
кэшируются с TTL по типу пути. Это отдельный домен от reconciliation_service.py
(тот сверяет 1С-документы) — не пересекается.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("reconciliation_proxy")


# ─────────────────────────── TTL-кэш ───────────────────────────
class _TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if time.time() >= expires:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._store[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        self._store.clear()


_cache = _TTLCache()

_MSTO_CACHE_TTL: dict[str, int] = {
    "/private/servicePoints": 7200,
    "/private/transactions": 600,
    "/private/tariffs": 3600,
}
_MSTO_CACHE_TTL_DEFAULT = 600


def _msto_ttl(url_path: str) -> int:
    if url_path in _MSTO_CACHE_TTL:
        return _MSTO_CACHE_TTL[url_path]
    for pattern, ttl in _MSTO_CACHE_TTL.items():
        if url_path.startswith(pattern):
            return ttl
    return _MSTO_CACHE_TTL_DEFAULT


def _cache_key(url_path: str, params: dict[str, Any] | None) -> str:
    params = params or {}
    sorted_params = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"msto:{url_path}?{sorted_params}"


def clear_cache() -> None:
    _cache.clear()


# ─────────────────────────── TradeCorp (JSON-RPC 2.0) ───────────────────────────
_tc_client: httpx.AsyncClient | None = None
_tc_token: str | None = None
_tc_token_expiry: float = 0.0
_tc_lock = asyncio.Lock()


def _tc_emitent() -> int:
    try:
        return int(get_settings().tradecorp_emitent_id)
    except (TypeError, ValueError):
        return 15


async def _tc_refresh_token() -> None:
    """Авторизация на processing API → Bearer-токен (~1 ч, обновляем за 5 мин)."""
    global _tc_token, _tc_token_expiry
    assert _tc_client is not None
    s = get_settings()
    resp = await _tc_client.post(
        "/v2",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "login",
            "params": {"login": s.tradecorp_login, "password": s.tradecorp_password},
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "Login failed"))
    _tc_token = data.get("result")
    _tc_token_expiry = time.time() + 55 * 60
    _tc_client.headers["Authorization"] = f"Bearer {_tc_token}"


async def _tc_get_client() -> httpx.AsyncClient:
    global _tc_client
    s = get_settings()
    if not (s.tradecorp_api_url and s.tradecorp_login and s.tradecorp_password):
        raise RuntimeError("Missing required TradeCorp API environment variables")
    if _tc_client is None:
        _tc_client = httpx.AsyncClient(
            base_url=s.tradecorp_api_url,
            timeout=60.0,
            headers={"Content-Type": "application/json"},
        )
    async with _tc_lock:
        if not _tc_token or time.time() >= _tc_token_expiry:
            await _tc_refresh_token()
    return _tc_client


def _tc_build_filter(date_from: str, date_to: str, station_ids: list | None) -> dict[str, Any]:
    # Operation IDs: 603=заправка, 614=возврат, 504=пополнение, 505=списание, 508=перевод, 511=корректировка
    flt: dict[str, Any] = {
        "operation": [{"equal": [603, 614, 504, 505, 508, 511]}],
        "date": [{"more": [f"{date_from} 00:00:00"], "less": [f"{date_to} 23:59:59"]}],
        "card": {"id": [{"unequal": [None]}]},  # только транзакции с картами
    }
    if station_ids:
        flt["station"] = {"number": [{"equal": station_ids}]}
    return flt


async def _tc_fetch_transactions(date_from: str, date_to: str, station_ids: list | None) -> list[dict]:
    client = await _tc_get_client()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "transactions_get",
        "params": {"emitent": _tc_emitent(), "filter": _tc_build_filter(date_from, date_to, station_ids), "calc": 1},
    }
    resp = await client.post("/v1", json=body)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "TradeCorp API Error"))
    return data.get("result") or []


def _num(value: Any) -> float:
    """cost/quantity/price из TradeCorp приходят в копейках/сотых долях → /100 (защита от null)."""
    return (value or 0) / 100


async def tradecorp_transactions(date_from: str, date_to: str, station_ids: list | None) -> dict[str, Any]:
    txs = await _tc_fetch_transactions(date_from, date_to, station_ids)
    normalized = [
        {
            "id": tx.get("id"),
            "date": tx.get("date"),
            "cardNumber": (tx.get("card") or {}).get("number") or (tx.get("identifier") or {}).get("number"),
            "cardId": (tx.get("card") or {}).get("id"),
            "stationId": (tx.get("station") or {}).get("id"),
            "stationNumber": (tx.get("station") or {}).get("number"),
            "stationName": (tx.get("station") or {}).get("name"),
            "operationName": tx.get("operation_name"),
            "quantity": _num(tx.get("quantity")),
            "cost": _num(tx.get("cost")),
            "price": _num(tx.get("price")),
            "cheque": [
                {
                    "productName": c.get("product_name"),
                    "quantity": _num(c.get("quantity")),
                    "cost": _num(c.get("cost")),
                    "price": _num(c.get("price")),
                }
                for c in (tx.get("cheque") or [])
            ],
        }
        for tx in txs
    ]
    return {"success": True, "count": len(normalized), "transactions": normalized}


async def tradecorp_summary(date_from: str, date_to: str, station_ids: list | None) -> dict[str, Any]:
    txs = await _tc_fetch_transactions(date_from, date_to, station_ids)
    summary: dict[str, Any] = {"totalCount": len(txs), "totalCost": 0.0, "totalQuantity": 0.0, "byStation": {}}
    for tx in txs:
        station_num = (tx.get("station") or {}).get("number") or "unknown"
        cost = _num(tx.get("cost"))
        qty = _num(tx.get("quantity"))
        summary["totalCost"] += cost
        summary["totalQuantity"] += qty
        st = summary["byStation"].setdefault(
            station_num,
            {"stationNumber": station_num, "stationName": (tx.get("station") or {}).get("name"), "count": 0, "cost": 0.0, "quantity": 0.0},
        )
        st["count"] += 1
        st["cost"] += cost
        st["quantity"] += qty
    summary["totalCost"] = round(summary["totalCost"], 2)
    for st in summary["byStation"].values():
        st["cost"] = round(st["cost"], 2)
    return {"success": True, "summary": summary}


async def tradecorp_health() -> dict[str, Any]:
    await _tc_get_client()  # прогрев/проверка токена
    return {
        "status": "ok",
        "emitentId": _tc_emitent(),
        "tokenValid": bool(_tc_token) and time.time() < _tc_token_expiry,
    }


# ─────────────────────────── MSTO IntegratorService (JWT) ───────────────────────────
@dataclass(frozen=True)
class MstoConn:
    base_url: str
    username: str
    password: str


# Кеш клиентов/токенов ПО ПОДКЛЮЧЕНИЮ (base_url|username): у каждого источника своё
# подключение MSTO; .env остаётся fallback'ом (если у источника креды не заданы).
_msto_clients: dict[str, dict[str, Any]] = {}
_msto_lock = asyncio.Lock()

_sp_map: dict[str, dict[str, Any]] = {}        # conn_key → {name(lower): id}
_sp_map_expiry: dict[str, float] = {}


def _msto_settings_conn() -> MstoConn | None:
    """Подключение MSTO из .env (settings) — fallback."""
    s = get_settings()
    if s.msto_api_url and s.msto_username and s.msto_password:
        return MstoConn(s.msto_api_url, s.msto_username, s.msto_password)
    return None


def _conn_key(conn: MstoConn) -> str:
    return f"{conn.base_url}|{conn.username}"


def _resolve_conn(conn: MstoConn | None) -> MstoConn:
    conn = conn or _msto_settings_conn()
    if conn is None:
        raise RuntimeError("Missing required MSTO credentials")
    return conn


async def _msto_refresh_token_for(conn: MstoConn) -> None:
    entry = _msto_clients[_conn_key(conn)]
    client: httpx.AsyncClient = entry["client"]
    client.headers.pop("Authorization", None)
    entry["token"] = None
    resp = await client.post("/session", json={"username": conn.username, "password": conn.password})
    resp.raise_for_status()
    token = (resp.json() or {}).get("item", {}).get("token")
    if not token:
        raise RuntimeError("MSTO API did not return a token")
    entry["token"] = token
    entry["expiry"] = time.time() + 23 * 60 * 60
    client.headers["Authorization"] = token


async def _msto_get_client(conn: MstoConn | None = None) -> httpx.AsyncClient:
    conn = _resolve_conn(conn)
    key = _conn_key(conn)
    entry = _msto_clients.get(key)
    if entry is None:
        entry = {
            "client": httpx.AsyncClient(
                base_url=conn.base_url, timeout=90.0,
                headers={"Content-Type": "application/json"},
            ),
            "token": None,
            "expiry": 0.0,
        }
        _msto_clients[key] = entry
    async with _msto_lock:
        if not entry["token"] or time.time() >= entry["expiry"]:
            await _msto_refresh_token_for(conn)
    return entry["client"]


async def _msto_invalidate_and_refresh(conn: MstoConn) -> None:
    entry = _msto_clients.get(_conn_key(conn))
    if entry:
        entry["token"] = None
        entry["expiry"] = 0.0
    await _msto_refresh_token_for(conn)


async def _msto_get_checked(url_path: str, params: dict[str, Any] | None = None,
                            conn: MstoConn | None = None) -> httpx.Response:
    """GET с автоповтором при 401 (рефреш токена)."""
    conn = _resolve_conn(conn)
    client = await _msto_get_client(conn)
    resp = await client.get(url_path, params=params)
    if resp.status_code == 401:
        await _msto_invalidate_and_refresh(conn)
        client = await _msto_get_client(conn)
        resp = await client.get(url_path, params=params)
    return resp


async def msto_conn_for_company(db: Any, company_id: Any) -> MstoConn | None:
    """Подключение MSTO из источника компании (source_type=msto): base_url+логин из
    connection_config, пароль из SourceCredentials (Fernet). None → используется .env."""
    from sqlalchemy import select
    from app.models import Source, SourceCredentials
    from app.services.onec.crypto import decrypt_password
    src = (await db.execute(select(Source).where(
        Source.company_id == company_id, Source.source_type == "msto"
    ))).scalars().first()
    if src is None:
        return None
    cfg = src.connection_config or {}
    base_url = cfg.get("base_url") or cfg.get("url")
    username = cfg.get("login") or cfg.get("username")
    cr = (await db.execute(select(SourceCredentials).where(
        SourceCredentials.source_id == src.id
    ))).scalars().first()
    enc = (cr.encrypted_values or {}) if cr else {}
    pwd = decrypt_password(enc["password"]) if enc.get("password") else None
    if base_url and username and pwd:
        return MstoConn(str(base_url), str(username), str(pwd))
    return None


async def get_service_points_map(conn: MstoConn | None = None) -> dict[str, Any]:
    """name(lower) → id; кэш 2 ч на подключение (обогащение transactions servicePointId)."""
    conn = _resolve_conn(conn)
    key = _conn_key(conn)
    if key in _sp_map and time.time() < _sp_map_expiry.get(key, 0.0):
        return _sp_map[key]
    try:
        resp = await _msto_get_checked("/private/servicePoints", conn=conn)
        models = (resp.json() or {}).get("models", []) if resp.status_code == 200 else []
        _sp_map[key] = {sp["name"].lower(): sp["id"] for sp in models if sp.get("name") and sp.get("id")}
        _sp_map_expiry[key] = time.time() + 2 * 60 * 60
        return _sp_map[key]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MSTO Proxy] Failed to load servicePoints map: %s", exc)
        return {}


async def msto_service_points(conn: MstoConn | None = None) -> Any:
    """Сырой ответ servicePoints; [] при 403/404/Access Denied (как в TF)."""
    resp = await _msto_get_checked("/private/servicePoints", conn=conn)
    if resp.status_code in (403, 404):
        return []
    if "Access Denied" in (resp.text or ""):
        return []
    resp.raise_for_status()
    return resp.json()


async def msto_tariffs(params: dict[str, Any] | None = None,
                       conn: MstoConn | None = None) -> Any:
    url_path = "/private/tariffs"
    key = _cache_key(url_path, params)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    resp = await _msto_get_checked(url_path, params, conn=conn)
    resp.raise_for_status()
    data = resp.json()
    _cache.set(key, data, _msto_ttl(url_path))
    return data


def _convert_date_to_msto(iso_date: str | None) -> str | None:
    """ISO/`YYYY-MM-DD` → `DD.MM.YYYY HH:MM:SS` (как convertDateToMstoFormat в TF)."""
    if not iso_date:
        return None
    if len(iso_date) >= 10 and iso_date[2] == "." and iso_date[5] == ".":
        return iso_date
    try:
        d = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return d.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None


def convert_transaction_params(query: dict[str, Any]) -> dict[str, Any]:
    """Конвертация query-параметров фронта в параметры MSTO API (как convertTransactionParams)."""
    q = dict(query)
    if q.get("dateFrom"):
        df = q["dateFrom"] if "T" in str(q["dateFrom"]) else f"{q['dateFrom']}T00:00:00"
        q["dateFrom"] = _convert_date_to_msto(df)
    if q.get("dateTo"):
        dt = q["dateTo"] if "T" in str(q["dateTo"]) else f"{q['dateTo']}T23:59:59"
        q["dateTo"] = _convert_date_to_msto(dt)
    if q.get("operationResults") and not q.get("operationResult"):
        results = q["operationResults"]
        results = results if isinstance(results, list) else str(results).split(",")
        q["operationResult"] = ",".join(results)
        q.pop("operationResults", None)
    if q.get("servicePointIds") and not q.get("servicePointId"):
        spids = q["servicePointIds"]
        q["servicePointId"] = ",".join(spids) if isinstance(spids, list) else str(spids)
        q.pop("servicePointIds", None)
    if not q.get("size"):
        q["size"] = "2000"
    return {k: v for k, v in q.items() if v is not None}


async def msto_transactions(query: dict[str, Any], conn: MstoConn | None = None) -> Any:
    """GET /private/transactions с конвертацией параметров, кэшем и обогащением servicePointId."""
    url_path = "/private/transactions"
    params = convert_transaction_params(query)
    key = _cache_key(url_path, params)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    sp_map = await get_service_points_map(conn)
    resp = await _msto_get_checked(url_path, params, conn=conn)
    resp.raise_for_status()
    data = resp.json()

    models = data.get("models") if isinstance(data, dict) else None
    if isinstance(models, list):
        for tx in models:
            if tx.get("servicePointName") and not tx.get("servicePointId"):
                sp_id = sp_map.get(str(tx["servicePointName"]).lower())
                if sp_id:
                    tx["servicePointId"] = sp_id

    _cache.set(key, data, _msto_ttl(url_path))
    return data
