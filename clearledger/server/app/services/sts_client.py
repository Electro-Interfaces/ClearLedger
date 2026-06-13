"""
HTTP-клиент для STS API (pos.autooplata.ru/tms).
Серверная версия — аналог frontend stsApiClient.ts.
"""

import time
from typing import Any

import httpx

# Кэш токена в памяти процесса
_token: str | None = None
_token_expiry: float = 0


async def _login(
    base_url: str, login: str, password: str
) -> str:
    """Получить JWT-токен от STS API."""
    global _token, _token_expiry

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/v2/login",
            json={
                "login": login,
                "password": password,
                "user": {"id": "00000000-0000-0000-0000-000000000000", "name": "System"},
            },
        )
        resp.raise_for_status()

    text = resp.text.strip().strip('"')
    if text.startswith("{"):
        import json
        obj = json.loads(text)
        text = obj.get("token", "")
    if not text:
        raise ValueError("Токен STS не получен")

    _token = text
    _token_expiry = time.time() + 18 * 60  # 18 минут
    return text


async def _get_token(base_url: str, login: str, password: str) -> str:
    """Получить токен из кэша или залогиниться."""
    global _token, _token_expiry
    if _token and time.time() < _token_expiry:
        return _token
    return await _login(base_url, login, password)


async def _auth_get(
    base_url: str, login: str, password: str, path: str
) -> Any:
    """GET-запрос с авторизацией и автоматическим re-login при 401."""
    token = await _get_token(base_url, login, password)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )

        if resp.status_code == 401:
            global _token, _token_expiry
            _token = None
            _token_expiry = 0
            token = await _login(base_url, login, password)
            resp = await client.get(
                f"{base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
            )

        resp.raise_for_status()
        return resp.json()


# ─── Public API ─────────────────────────────────────────────


async def sts_get_shifts(
    base_url: str, login: str, password: str,
    system: int, station: int | None = None,
) -> list[dict]:
    """Список смен."""
    params = f"system={system}"
    if station is not None:
        params += f"&station={station}"
    return await _auth_get(base_url, login, password, f"/v1/shifts?{params}")


async def sts_get_shift_report(
    base_url: str, login: str, password: str,
    system: int, station: int, shift: int,
) -> dict:
    """Детальный сменный отчёт."""
    params = f"system={system}&station={station}&shift={shift}"
    return await _auth_get(base_url, login, password, f"/v1/report/shift_report?{params}")


async def sts_get_receipts(
    base_url: str, login: str, password: str,
    system: int, station: int, shift: int,
) -> list[dict]:
    """ТТН (поступления) по смене."""
    params = f"system={system}&station={station}&shift={shift}"
    return await _auth_get(base_url, login, password, f"/v1/report/receipts?{params}")


async def sts_get_transactions(
    base_url: str, login: str, password: str,
    system: int, date_from: str, date_to: str, station: int | None = None,
) -> list[dict]:
    """Пооперационные транзакции отпуска на ТРК (TF) — STS /v2/transactions.

    Опорный поток (anchor) для разрезов corp_fuel/online_fuel. Ответ STS —
    блоки по станциям [{number, items:[...]}]; возвращаем плоский список
    items с проставленной станцией.
    """
    from urllib.parse import urlencode
    q: dict[str, Any] = {
        "system": system,
        "dt_beg": f"{date_from} 00:00:00",
        "dt_end": f"{date_to} 23:59:59",
    }
    if station is not None:
        q["station"] = station
    data = await _auth_get(base_url, login, password, f"/v2/transactions?{urlencode(q)}")
    flat: list[dict] = []
    if isinstance(data, list):
        for block in data:
            num = (block or {}).get("number")
            for tx in (block.get("items") or []):
                t = dict(tx)
                t.setdefault("station", num)
                flat.append(t)
    return flat


async def sts_test_connection(
    base_url: str, login: str, password: str, system: int,
) -> dict:
    """Тест подключения — логин + получение списка смен."""
    try:
        await _login(base_url, login, password)
        shifts = await sts_get_shifts(base_url, login, password, system)
        return {"ok": True, "shifts_count": len(shifts)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
