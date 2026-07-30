"""
HTTP-клиент для STS API (pos.autooplata.ru/tms).
Серверная версия — аналог frontend stsApiClient.ts.
"""

import time
from typing import Any

import httpx

# Кэш токенов в памяти процесса. КЛЮЧ = (base_url, login): иначе токен одного
# STS-аккаунта протекал бы на запросы другого канала/компании в том же воркере
# (общий модульный глобал) → нормализация под чужим аккаунтом.
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


async def _login(
    base_url: str, login: str, password: str
) -> str:
    """Получить JWT-токен от STS API."""
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

    _token_cache[(base_url, login)] = (text, time.time() + 18 * 60)  # 18 минут
    return text


async def _get_token(base_url: str, login: str, password: str) -> str:
    """Получить токен из кэша (по base_url+login) или залогиниться."""
    cached = _token_cache.get((base_url, login))
    if cached and time.time() < cached[1]:
        return cached[0]
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
    date_from: str | None = None, date_to: str | None = None,
) -> list[dict]:
    """Список смен за период.

    ВАЖНО: STS /v1/shifts фильтрует по dt_beg/dt_end (ISO с временем), НЕ по
    date_from/date_to. С неверными именами параметров STS их игнорирует и
    отдаёт лишь последние смены — поэтому загрузка за прошлые месяцы давала 0
    (эталон — TradeFrame shiftsService: dt_beg='2026-04-01T00:00:00').
    date_from/date_to сюда приходят как YYYY-MM-DD.
    """
    params = f"system={system}"
    if station is not None:
        params += f"&station={station}"
    if date_from:
        params += f"&dt_beg={date_from}T00:00:00"
    if date_to:
        params += f"&dt_end={date_to}T23:59:59"
    return await _auth_get(base_url, login, password, f"/v1/shifts?{params}")


async def sts_get_tanks(
    base_url: str, login: str, password: str, system: int, station: int,
) -> list[dict]:
    """Резервуары станции — STS /v1/tanks. Отсюда берётся ПАСПОРТНАЯ ёмкость.

    `volume_max` — вместимость резервуара (её же «Монитор» показывает как «Ёмкость»);
    без неё границу достоверности замера приходится оценивать по книге, а книга на
    части станций сама завышена. Плюс текущий уровень, температура, плотность и
    подтоварная вода — то же, что в сменном отчёте, но на момент запроса.
    """
    params = f"system={system}&station={station}"
    data = await _auth_get(base_url, login, password, f"/v1/tanks?{params}")
    return data if isinstance(data, list) else []


async def sts_get_coupons(
    base_url: str, login: str, password: str,
    system: int, station: int | None = None,
    dt_beg: str | None = None, dt_end: str | None = None,
) -> list[dict]:
    """Купоны станции за период — STS /v1/coupons (dt_beg/dt_end как 'YYYY-MM-DD HH:MM:SS').

    Купоны живут только в STS: в реализации остаётся номер купона, а дату его выдачи
    и остаток знает лишь этот справочник. Ответ — блоки по станциям
    ({system, number, coupons[], total}); возвращаем плоский список, проставляя
    каждому купону номер станции из блока (без него сеть не разложить по АЗС).
    Без `station` STS отдаёт всю сеть системы одним запросом.
    """
    from urllib.parse import urlencode
    q: dict[str, Any] = {"system": system}
    if station is not None:
        q["station"] = station
    if dt_beg:
        q["dt_beg"] = dt_beg
    if dt_end:
        q["dt_end"] = dt_end
    data = await _auth_get(base_url, login, password, f"/v1/coupons?{urlencode(q)}")
    blocks = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    flat: list[dict] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        num = block.get("number", station)
        for c in (block.get("coupons") or []):
            if isinstance(c, dict):
                item = dict(c)
                item.setdefault("station", num)
                flat.append(item)
    return flat


async def sts_get_points(
    base_url: str, login: str, password: str, system: int,
) -> list[dict]:
    """Все торговые точки (станции) системы — STS GET /v1/points?system=.

    Авто-discovery всей сети: канал работает со ВСЕМИ станциями системы, а не
    с зашитым подмножеством. Точка: {system, number (код станции), name,
    address, longitude, latitude}.
    """
    data = await _auth_get(base_url, login, password, f"/v1/points?system={system}")
    return data if isinstance(data, list) else []


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
    """ТТН (поступления) по смене — плоский список позиций приёма.

    STS отдаёт вложенную форму [{system, number, shifts:[{number, receipt:[...]}]}];
    разворачиваем в плоский список ТТН-позиций, проставляя номер смены.
    """
    params = f"system={system}&station={station}&shift={shift}"
    data = await _auth_get(base_url, login, password, f"/v1/report/receipts?{params}")
    flat: list[dict] = []
    if isinstance(data, list):
        for block in data:
            if not isinstance(block, dict):
                continue
            for sh in (block.get("shifts") or []):
                for rc in (sh.get("receipt") or []):
                    item = dict(rc)
                    item.setdefault("shift", sh.get("number"))
                    flat.append(item)
    elif isinstance(data, dict):
        # на случай иной (плоской) формы ответа
        for rc in (data.get("receipt") or []):
            flat.append(dict(rc))
    return flat


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
