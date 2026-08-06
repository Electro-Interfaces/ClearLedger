"""Рабочее место станции внутри «Магазина».

Менеджер из центра открывает веб станционного агента и работает в нём как на
месте: приёмка, инвентаризация, остатки, карточки. Это не копия экранов, а сам
агент — источник правды станции.

Путь запроса:

    браузер → /api/store/station/{id}/console/...   (здесь: права, имя человека)
            → хаб TradeLink /integration/stations/{id}/console/...
            → WireGuard overlay → веб агента на ноде

Почему через хаб, а не напрямую: станция за CGNAT, входящих соединений к ней
нет и не будет. Единственный, кто её видит, — хаб, у которого туннель до ноды
уже поднят. Пароль рабочего места живёт на хабе и наружу не выходит; отсюда
уходит только имя пользователя, чтобы документы на станции были подписаны им,
а не безличным «оператором».

Ответ станции переписывается по дороге: агент строит ссылки от корня своего
веба (`/stock`, `/item/…`), а в браузере он живёт под префиксом. Без правки
адресов первая же ссылка увела бы менеджера из станции в корень «Магазина».
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.deps import scope_company_id
from app.models import User

router = APIRouter(prefix="/store/station", tags=["станция"])

HUB_URL = os.environ.get("TRADELINK_HUB_URL", "https://link.dataworker.ru")
HUB_KEY = os.environ.get("TRADELINK_INTEGRATION_KEY", "")

# Заголовки, которые нельзя переносить как есть: hop-by-hop и всё, что описывает
# уже раскодированное тело.
СЛУЖЕБНЫЕ = {"content-encoding", "content-length", "transfer-encoding", "connection"}

# Рабочее место открывается в рамке приложения, а рамка не носит с собой токен:
# он живёт в localStorage и уходит заголовком, которого у обычной навигации нет.
# Поэтому вход в станцию открывается один раз — обменом токена на короткую
# cookie-сессию, привязанную к конкретной АЗС.
COOKIE = "station_console"
# Час БЕЗДЕЙСТВИЯ, а не час работы: cookie продлевается на каждом запросе
# (см. _поставить_cookie). Иначе приёмка на двести позиций упирается в
# «сессия истекла» на середине, и введённое приходится набирать заново.
СЕССИЯ_МИНУТ = 60


def _выдать_сессию(user: User, station_id: int) -> str:
    payload = {
        "sub": str(user.id),
        "station": station_id,
        "name": (user.name or user.email or "").strip(),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=СЕССИЯ_МИНУТ),
        "iat": datetime.now(timezone.utc),
        "typ": "station_console",
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=get_settings().algorithm)


def _выдать_сессию_из_имени(name: str, station_id: int) -> str:
    """Продление: тот же владелец и станция, новый срок.

    Пользователя из базы не перечитываем — сессия уже подписана нами, и права
    проверены при её выдаче. Ходить в базу на каждой картинке рабочего места
    значило бы платить запросом за каждый килобайт.
    """
    payload = {
        "sub": "", "station": station_id, "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=СЕССИЯ_МИНУТ),
        "iat": datetime.now(timezone.utc), "typ": "station_console",
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=get_settings().algorithm)


def _имя_из_сессии(request: Request, station_id: int) -> str | None:
    """Кто работает по cookie-сессии. None — сессии нет или она чужая."""
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, get_settings().secret_key, algorithms=[get_settings().algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "station_console" or int(payload.get("station", -1)) != station_id:
        return None
    return str(payload.get("name") or "")


def _префикс(station_id: int) -> str:
    return f"/api/store/station/{station_id}/console"


def _поставить_cookie(ответ: Response, token: str, station_id: int) -> None:
    ответ.set_cookie(
        COOKIE, token, max_age=СЕССИЯ_МИНУТ * 60, httponly=True,
        samesite="lax", secure=True, path=_префикс(station_id),
    )


# Страница вместо JSON, когда сессии нет.
#
# Рабочее место открыто отдельной вкладкой, и её жизнь длиннее часа: человек
# уходит на склад, возвращается, жмёт «Провести» — и получает
# {"detail":"сессия работы на станции не открыта или истекла"} без единого
# способа что-то сделать. Тупик.
#
# Вкладка живёт на том же домене, что и «Магазин», значит токен приложения ей
# доступен: страница сама открывает сессию заново и возвращает человека туда,
# где он был. Если токена нет (зашли по ссылке из другого браузера) — честно
# отправляем в центр, а не оставляем с JSON-ом.
СТРАНИЦА_СЕССИИ = """<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Рабочее место АЗС {station}</title>
<body style="font:16px/1.55 system-ui;max-width:640px;margin:70px auto;padding:0 20px;
             background:#0f1115;color:#dfe3ea">
<h2 style="font-size:20px">Сессия работы на АЗС {station} истекла</h2>
<p id="что">Восстанавливаю вход…</p>
<p><a id="назад" href="/" style="color:#6aa9ff">Вернуться в «Магазин»</a></p>
<script>
const token = localStorage.getItem('clearledger-token')
const что = document.getElementById('что')
if (!token) {{
  что.textContent = 'Войдите в «Магазин» и откройте станцию кнопкой «Работать» — '
    + 'эта вкладка открыта без входа в приложение.'
}} else {{
  fetch('/api/store/station/{station}/session', {{
    method: 'POST', headers: {{ Authorization: 'Bearer ' + token }},
  }}).then((r) => {{
    if (!r.ok) throw new Error('код ' + r.status)
    location.reload()
  }}).catch((e) => {{
    что.textContent = 'Не удалось восстановить вход: ' + e.message
      + '. Откройте станцию заново из «Магазина».'
  }})
}}
</script></body></html>"""


def _переписать(html: str, prefix: str) -> str:
    """Адреса станции — под префикс прокси.

    Правится ровно то, что ведёт на корень: href/action/src, fetch и JS-навигация
    location='/…' (клик по строке документа: списки открывают карточку именно ей,
    и без правки клик по УПД уходил на корень пространства — 404). Схемы (http://,
    //, mailto:) и якоря не трогаем.
    """
    html = re.sub(r'(href|action|src)="/(?!/)', rf'\1="{prefix}/', html)
    html = html.replace('fetch("/', f'fetch("{prefix}/')
    # location='/…' и location="/…" (навигация по клику на строку) — под префикс.
    html = re.sub(r"location\s*=\s*(['\"])/(?!/)", rf"location=\1{prefix}/", html)
    return html


@router.post("/{station_id}/session")
async def station_console_session(
    station_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Открыть сессию работы на станции.

    Вызывается с обычным токеном приложения — и ставит cookie, с которой рамка
    рабочего места уже ходит сама. Cookie привязана к станции и живёт час:
    вернуться к работе на другой АЗС без нового входа нельзя, а забытая
    вкладка перестаёт быть доступом сама.
    """
    await scope_company_id(user, db)
    ответ = Response(status_code=204)
    _поставить_cookie(ответ, _выдать_сессию(user, station_id), station_id)
    return ответ


@router.api_route(
    "/{station_id}/console/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "HEAD"],
)
async def station_console(
    station_id: int,
    path: str,
    request: Request,
) -> Response:
    """Прокси к рабочему месту станции."""
    # Права проверены при выдаче сессии; здесь достаточно её подписи. Иначе
    # каждая картинка и каждая форма станции требовали бы заголовка, которого у
    # навигации в рамке нет.
    автор = _имя_из_сессии(request, station_id)
    if автор is None:
        # Страницу отдаём людям, JSON — фоновым запросам самой станции: скрипт
        # рабочего места должен получить понятный код, а не HTML в ответ.
        if "text/html" in request.headers.get("accept", ""):
            return Response(
                content=СТРАНИЦА_СЕССИИ.format(station=station_id),
                status_code=401, media_type="text/html; charset=utf-8",
            )
        raise HTTPException(401, "сессия работы на станции не открыта или истекла")
    if not HUB_KEY:
        raise HTTPException(503, "не настроен ключ интеграции с хабом TradeLink")

    заголовки = {
        "X-Integration-Key": HUB_KEY,
        # Фамилия едет процентным кодированием: заголовки HTTP — latin-1, а имя
        # русское, и без этого прокси падает на первом же «Жукова».
        "X-Ledger-User": quote(автор, safe=""),
    }
    if ct := request.headers.get("content-type"):
        заголовки["content-type"] = ct
    if acc := request.headers.get("accept"):
        заголовки["accept"] = acc

    тело = await request.body()
    цель = f"{HUB_URL}/api/v1/integration/stations/{station_id}/console/{path}"

    try:
        async with httpx.AsyncClient(timeout=40.0, follow_redirects=False) as client:
            ответ = await client.request(
                request.method, цель, params=dict(request.query_params),
                headers=заголовки, content=тело or None,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(504, f"станция {station_id} не ответила: {exc}") from exc

    prefix = _префикс(station_id)
    исходящие = {k: v for k, v in ответ.headers.items() if k.lower() not in СЛУЖЕБНЫЕ}

    # Переезд станции («документ проведён → вернись к списку») обязан остаться
    # внутри рабочей области, а не выкинуть менеджера в корень приложения.
    if location := ответ.headers.get("location"):
        if location.startswith("/") and not location.startswith(prefix):
            исходящие["location"] = f"{prefix}{location}"

    тип = ответ.headers.get("content-type", "")
    if тип.startswith("text/html"):
        итог = Response(
            content=_переписать(ответ.text, prefix),
            status_code=ответ.status_code,
            headers=исходящие,
            media_type=тип,
        )
    else:
        итог = Response(content=ответ.content, status_code=ответ.status_code,
                        headers=исходящие, media_type=тип or None)

    # Сессия продлевается работой: час отсчитывается от последнего действия, а
    # не от входа. Товаровед считает склад дольше часа, и обрывать его посреди
    # инвентаризации значит терять пересчёт.
    _поставить_cookie(итог, _выдать_сессию_из_имени(автор, station_id), station_id)
    return итог


@router.get("/{station_id}/state")
async def station_state(
    station_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """На связи ли станция — чтобы кнопка не открывала пустое окно.

    Спрашиваем хаб, а не агента: хаб знает состояние туннеля, и его ответ
    приходит сразу, тогда как мёртвая станция отвечала бы таймаутом.
    """
    await scope_company_id(user, db)
    if not HUB_KEY:
        return {"station_id": station_id, "online": False, "reason": "нет ключа интеграции с хабом"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{HUB_URL}/api/v1/integration/stations/{station_id}/console/",
                headers={"X-Integration-Key": HUB_KEY},
            )
    except httpx.HTTPError as exc:
        return {"station_id": station_id, "online": False, "reason": str(exc)}
    if r.status_code == 200:
        return {"station_id": station_id, "online": True, "url": f"{_префикс(station_id)}/"}
    причина = "станция не на связи"
    try:
        причина = r.json().get("error") or причина
    except ValueError:
        pass
    return {"station_id": station_id, "online": False, "reason": причина}
