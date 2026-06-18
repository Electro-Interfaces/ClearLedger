"""
HubEx FSM адаптер — сервисные заявки/ремонты по объекту (asset).

Сервисный токен берётся из конфига (env HUBEX_SERVICE_TOKEN), НАРУЖУ не уходит.
access_token кэшируется ~25 мин (HubEx выдаёт 1800с). Заявки станции =
GET /WORK/Tasks?assetID={asset_id}; asset_id = ServiceLocation.metadata.hubexAssetId
(совпадает с HubEx asset.id — проверено на проде).
"""
import asyncio
import time
from typing import Any

import httpx

from app.config import get_settings

_token: str | None = None
_token_exp: float = 0.0
_lock = asyncio.Lock()


def is_configured() -> bool:
    return bool(get_settings().hubex_service_token)


def _headers(auth: str | None = None) -> dict[str, str]:
    h = {"Accept": "application/json", "X-Application-ID": get_settings().hubex_app_id}
    if auth:
        h["Authorization"] = f"Bearer {auth}"
    return h


async def _access_token() -> str:
    """Действующий access_token (с авто-переавторизацией по сервисному токену)."""
    global _token, _token_exp
    async with _lock:
        if _token and time.monotonic() < _token_exp:
            return _token
        s = get_settings()
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                f"{s.hubex_base_url}/AUTHZ/AccessTokens",
                json={"ServiceToken": s.hubex_service_token},
                headers={**_headers(), "Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
        _token = data["access_token"]
        # перевыпуск за 5 мин до истечения
        _token_exp = time.monotonic() + max(60, int(data.get("expires_in", 1800)) - 300)
        return _token


def _norm_task(t: dict) -> dict[str, Any]:
    st = t.get("taskStatus") or {}
    cr = t.get("actualCriticality") or {}
    assignee = t.get("assignedTo") or {}
    ts = t.get("timesheet") or {}
    name = " ".join(x for x in (assignee.get("lastName"), assignee.get("firstName")) if x).strip()
    return {
        "id": t.get("id"),
        "number": t.get("number"),
        "status": st.get("name"),
        "statusColor": st.get("color"),
        "type": (t.get("taskType") or {}).get("name"),
        "workType": (t.get("workType") or {}).get("name"),
        "criticality": cr.get("name"),
        "criticalityColor": cr.get("color"),
        "assignee": name or None,
        "notes": t.get("notes"),
        "location": (t.get("location") or {}).get("address"),
        "deadline": ts.get("deadline"),
        "created": ts.get("created"),
        "lastModified": t.get("lastModified"),
    }


async def get_asset_tasks(asset_id: int, limit: int | None = None) -> dict[str, Any]:
    """Заявки HubEx по объекту (asset_id). Возвращает {tasks: [...], total: int}."""
    if not is_configured():
        return {"tasks": [], "total": 0}
    s = get_settings()
    lim = limit or s.hubex_tasks_limit
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(
            f"{s.hubex_base_url}/WORK/Tasks",
            params={"assetID": asset_id},
            headers={**_headers(token), "Range": f"items=0-{lim - 1}"},
        )
    if r.status_code not in (200, 206):
        r.raise_for_status()
    data = r.json()
    items = list(data.values()) if isinstance(data, dict) else (data or [])
    total = len(items)
    content_range = r.headers.get("Content-Range", "")  # items=FROM-TILL/TOTAL
    if "/" in content_range:
        try:
            total = int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    return {"tasks": [_norm_task(t) for t in items], "total": total}
