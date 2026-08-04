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

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.deps import scope_company_id
from app.models import User

router = APIRouter(prefix="/store/station", tags=["станция"])

HUB_URL = os.environ.get("TRADELINK_HUB_URL", "https://link.dataworker.ru")
HUB_KEY = os.environ.get("TRADELINK_INTEGRATION_KEY", "")

# Заголовки, которые нельзя переносить как есть: hop-by-hop и всё, что описывает
# уже раскодированное тело.
СЛУЖЕБНЫЕ = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def _префикс(station_id: int) -> str:
    return f"/api/store/station/{station_id}/console"


def _переписать(html: str, prefix: str) -> str:
    """Адреса станции — под префикс прокси.

    Правится ровно то, что ведёт на корень: href/action/src и fetch в скриптах
    рабочего места. Схемы (http://, //, mailto:) и якоря не трогаем.
    """
    html = re.sub(r'(href|action|src)="/(?!/)', rf'\1="{prefix}/', html)
    html = html.replace('fetch("/', f'fetch("{prefix}/')
    return html


@router.api_route(
    "/{station_id}/console/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "HEAD"],
)
async def station_console(
    station_id: int,
    path: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Прокси к рабочему месту станции."""
    await scope_company_id(user, db)  # право на компанию проверяется здесь же
    if not HUB_KEY:
        raise HTTPException(503, "не настроен ключ интеграции с хабом TradeLink")

    # Имя человека едет на станцию: там оно станет автором документа. Фамилия
    # понятнее адреса — в журнале станции его читает товаровед, а не админ.
    автор = (user.name or user.email or "").strip()

    заголовки = {
        "X-Integration-Key": HUB_KEY,
        "X-Ledger-User": автор,
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
        return Response(
            content=_переписать(ответ.text, prefix),
            status_code=ответ.status_code,
            headers=исходящие,
            media_type=тип,
        )
    return Response(content=ответ.content, status_code=ответ.status_code,
                    headers=исходящие, media_type=тип or None)


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
