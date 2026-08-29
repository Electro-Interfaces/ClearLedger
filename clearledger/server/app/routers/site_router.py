"""«Сайт»: публичная витрина компании и кабинет её клиента.

Граница между сайтом и пространством проходит так:

* **Вход держит сайт** (elsyplus.ru): код на почту, сессия в куке, одноразовый
  пропуск в стенд, журнал показов. Это его механика и его безопасность.
* **Содержимое ведёт пространство**: кто вхож в кабинет и с каким уровнем, какие
  стенды ему открыты, есть ли у него СВОЁ пространство и куда его пускать.

Кабинет — прихожая, а не рабочее место (решение МАГа 29.08.2026). Каждому клиенту
разворачивается своё пространство, и работает он там. Поэтому договоры, акты и
сверки в кабинет НЕ возятся: они у клиента и так есть, в его собственном контуре, и
возить их второй раз значит заводить вторую правду. В кабинете остаётся ровно две
вещи: дверь в своё пространство и разговор с нами.

Отсюда два направления, и оба в этом файле:

* `/site/...` — пространство читает сайт (что там написали, кто заходил).
  Ходит по адресу из реестра коннекторов (`connectors`, тип `site`) с ключом из
  окружения (`SITE_SERVICE_TOKEN`) — правило docs/CORE.md §7а.
* `/site/pull/...` — сайт читает пространство тем же ключом. Сессии там нет и быть
  не может: спрашивает сервер сайта, а не человек.

Что сюда НЕ переносится: страницы сайта, тексты и картинки. Это работа сайта, и
редактор ей не нужен.
"""
from __future__ import annotations

import os
import secrets
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    ClientSpace, Connector, Counterparty, SiteCabinetUser, SiteDemo, User,
)
from app.services import space_projection

router = APIRouter(prefix="/site", tags=["Сайт"])

CONNECTOR_TYPE = "site"
DEFAULT_TIMEOUT = 15.0
# Ручки сайта. Читаем только чтение: пространство ничего на сайте не меняет.
PATHS = {
    "requests": "/api/admin/requests",
    "cabinets": "/api/admin/users",
    "demos": "/api/admin/demo-log",
}


class SiteUnavailable(HTTPException):
    """Сайт не отвечает или не подключён — не ошибка пространства, а состояние связи.

    Отдаём 200 с пустым содержимым и причиной вместо 5xx: экран должен открыться и
    сказать, почему пусто, а не показать человеку красную страницу приложения.
    """


async def _connector(db: AsyncSession, cid: uuid.UUID) -> Connector | None:
    res = await db.execute(
        select(Connector).where(
            Connector.company_id == cid, Connector.type == CONNECTOR_TYPE,
            Connector.status != "disabled",
        ).order_by(Connector.created_at)
    )
    return res.scalars().first()


def _token(conn: Connector) -> str:
    """Ключ доступа к сайту: общий или свой у компании (`config.cred_ref`).

    Общая переменная остаётся фолбэком, поэтому одиночный стек ничего не настраивает
    сверх одной строки в `.env`.
    """
    ref = (conn.config or {}).get("cred_ref")
    if ref:
        own = os.getenv(f"{ref}_SERVICE_TOKEN")
        if own:
            return own
    return os.getenv("SITE_SERVICE_TOKEN", "")


async def _read(db: AsyncSession, cid: uuid.UUID, key: str) -> dict[str, Any]:
    """Прочитать раздел сайта. Ответ всегда одной формы: данные + состояние связи."""
    conn = await _connector(db, cid)
    if conn is None or not conn.url:
        return {"items": [], "connected": False,
                "reason": "Сайт не подключён: заведите коннектор в «Подключениях»"}
    token = _token(conn)
    if not token:
        return {"items": [], "connected": False,
                "reason": "Нет служебного ключа сайта (SITE_SERVICE_TOKEN в окружении стека)"}

    url = f"{conn.url.rstrip('/')}{PATHS[key]}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers={"X-Space-Token": token})
    except httpx.HTTPError as e:
        return {"items": [], "connected": False, "reason": f"Сайт не отвечает: {e}"}
    if resp.status_code == 403:
        return {"items": [], "connected": False,
                "reason": "Сайт не принял ключ пространства"}
    if resp.status_code >= 400:
        return {"items": [], "connected": False,
                "reason": f"Сайт ответил {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"items": [], "connected": False, "reason": "Сайт ответил не JSON"}
    items = data if isinstance(data, list) else data.get("items", [])
    return {"items": items, "connected": True, "reason": None, "url": conn.url}


@router.get("/requests")
async def site_requests(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Обращения из кабинета сайта: кто написал, о чём и по какому продукту."""
    cid = await assert_company_product(company_id, user, db, "site")
    return await _read(db, cid, "requests")


@router.get("/cabinets")
async def site_cabinets(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кто заведён в кабинете сайта: адрес, уровень доступа, компания."""
    cid = await assert_company_product(company_id, user, db, "site")
    return await _read(db, cid, "cabinets")


@router.get("/demos")
async def site_demos(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Журнал демо-стендов: кому и когда открывали показ."""
    cid = await assert_company_product(company_id, user, db, "site")
    return await _read(db, cid, "demos")


@router.get("/summary")
async def site_summary(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сводка первого экрана: сколько обращений, кабинетов и показов.

    Одним ответом, а не тремя запросами с клиента: три числа на одном экране должны
    быть посчитаны на один момент времени, иначе они спорят между собой.
    """
    cid = await assert_company_product(company_id, user, db, "site")
    out: dict[str, Any] = {"connected": True, "reason": None}
    for key in PATHS:
        part = await _read(db, cid, key)
        out[key] = len(part["items"])
        if not part["connected"]:
            out["connected"] = False
            out["reason"] = part["reason"]
            out[key] = 0
        else:
            out.setdefault("url", part.get("url"))
    return out


# ── Управление кабинетом: люди клиента и стенды ──────────────────────────────
# Ведёт человек в приложении «Сайт». Сайт эти записи только читает (`/site/pull/...`).


class CabinetUserIn(BaseModel):
    email: str
    level: str = "guest"
    counterparty_id: str | None = None
    demos: list[str] = Field(default_factory=list)
    note: str | None = None
    is_active: bool = True


LEVELS = {"guest", "client", "partner", "admin"}


def _cabinet_card(row: SiteCabinetUser, client: Counterparty | None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "email": row.email,
        "level": row.level,
        "counterpartyId": str(row.counterparty_id) if row.counterparty_id else None,
        "counterpartyName": client.name if client else None,
        "counterpartyInn": client.inn if client else None,
        "demos": list(row.demos or []),
        "note": row.note,
        "isActive": row.is_active,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/cabinet-users")
async def cabinet_users(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кому открыт кабинет: адрес, уровень, клиент, доступные стенды."""
    cid = await assert_company_product(company_id, user, db, "site")
    res = await db.execute(
        select(SiteCabinetUser, Counterparty)
        .outerjoin(Counterparty, Counterparty.id == SiteCabinetUser.counterparty_id)
        .where(SiteCabinetUser.company_id == cid)
        .order_by(SiteCabinetUser.email)
    )
    return {"items": [_cabinet_card(row, client) for row, client in res.all()]}


@router.post("/cabinet-users")
async def cabinet_user_add(
    payload: CabinetUserIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Завести или переписать доступ. Ключ — адрес: два доступа одному человеку
    означали бы, что ответ «что ему видно» зависит от порядка выборки."""
    cid = await assert_company_product(company_id, user, db, "site")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Нужен почтовый адрес")
    if payload.level not in LEVELS:
        raise HTTPException(400, f"Неизвестный уровень: {payload.level}")

    row = (await db.execute(select(SiteCabinetUser).where(
        SiteCabinetUser.company_id == cid, SiteCabinetUser.email == email,
    ))).scalar_one_or_none()
    if row is None:
        row = SiteCabinetUser(company_id=cid, email=email, created_by=user.id)
        db.add(row)
    row.level = payload.level
    row.counterparty_id = uuid.UUID(payload.counterparty_id) if payload.counterparty_id else None
    row.demos = list(payload.demos or [])
    row.note = payload.note
    row.is_active = payload.is_active
    await db.commit()
    await db.refresh(row)
    client = None
    if row.counterparty_id:
        client = (await db.execute(select(Counterparty).where(
            Counterparty.id == row.counterparty_id))).scalar_one_or_none()
    return _cabinet_card(row, client)


@router.delete("/cabinet-users/{row_id}")
async def cabinet_user_drop(
    row_id: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Закрыть доступ. Записи сайта (сессии, журнал показов) это не трогает —
    там свой хозяин; но следующий вход уже не пройдёт проверку уровня."""
    cid = await assert_company_product(company_id, user, db, "site")
    row = (await db.execute(select(SiteCabinetUser).where(
        SiteCabinetUser.id == uuid.UUID(row_id), SiteCabinetUser.company_id == cid,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Доступ не найден")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


class DemoIn(BaseModel):
    code: str
    title: str
    description: str | None = None
    upstream_url: str | None = None
    external_url: str | None = None
    landing: str | None = None
    is_enabled: bool = True
    sort: int = 100


def _demo_card(row: SiteDemo) -> dict[str, Any]:
    return {
        "id": str(row.id), "code": row.code, "title": row.title,
        "description": row.description, "upstreamUrl": row.upstream_url,
        "externalUrl": row.external_url, "landing": row.landing,
        "isEnabled": row.is_enabled, "sort": row.sort,
    }


@router.get("/demo-stands")
async def demo_stands(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Каталог стендов: что вообще можно показать клиенту."""
    cid = await assert_company_product(company_id, user, db, "site")
    res = await db.execute(select(SiteDemo).where(SiteDemo.company_id == cid)
                           .order_by(SiteDemo.sort, SiteDemo.title))
    return {"items": [_demo_card(r) for r in res.scalars().all()]}


@router.post("/demo-stands")
async def demo_stand_save(
    payload: DemoIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Завести стенд или переписать его. Код неизменен — по нему сайт строит путь
    прохода `/demo-run/<код>/app/`, и смена кода порвала бы живые ссылки."""
    cid = await assert_company_product(company_id, user, db, "site")
    code = payload.code.strip().lower()
    if not code:
        raise HTTPException(400, "Нужен код стенда")
    row = (await db.execute(select(SiteDemo).where(
        SiteDemo.company_id == cid, SiteDemo.code == code))).scalar_one_or_none()
    if row is None:
        row = SiteDemo(company_id=cid, code=code)
        db.add(row)
    row.title = payload.title
    row.description = payload.description
    row.upstream_url = payload.upstream_url
    row.external_url = payload.external_url
    row.landing = payload.landing
    row.is_enabled = payload.is_enabled
    row.sort = payload.sort
    await db.commit()
    await db.refresh(row)
    return _demo_card(row)


# ── Обратное направление: сайт читает пространство ───────────────────────────
# Спрашивает СЕРВЕР сайта своим ключом, поэтому сессии здесь нет. Компания —
# та, у которой заведён коннектор сайта: пространство одно, сайт один.


async def _pull_company(db: AsyncSession, token: str | None) -> uuid.UUID:
    """Проверить ключ и понять, чьё это пространство.

    Сравнение постоянного времени: разница в скорости ответа на неверный ключ —
    это подсказка подбирающему, а ключ здесь открывает список клиентов.
    """
    expected = os.getenv("SITE_SERVICE_TOKEN", "")
    if len(expected) < 16 or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(403, "Ключ сайта не принят")
    res = await db.execute(select(Connector).where(
        Connector.type == CONNECTOR_TYPE, Connector.status != "disabled"))
    conns = res.scalars().all()
    if not conns:
        raise HTTPException(404, "Коннектор сайта не заведён")
    if len({c.company_id for c in conns}) > 1:
        # Несколько компаний с сайтом в одном контейнере: у каждой должен быть свой
        # ключ (`config.cred_ref`), иначе один сайт увидит документы соседней.
        raise HTTPException(409, "Сайт заведён у нескольких компаний — нужен свой ключ")
    return conns[0].company_id


@router.get("/pull/cabinet")
async def pull_cabinet(
    email: str = Query(...),
    x_space_token: str | None = Header(None, alias="X-Space-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кто это и что ему открыто. Сайт спрашивает при входе и при показе кабинета.

    Незаведённому отвечаем тем же по форме ответом с уровнем `guest`: по различию
    ответов нельзя собрать список наших клиентов — то же правило, что у сайта на
    отправке кода.
    """
    cid = await _pull_company(db, x_space_token)
    addr = email.strip().lower()
    row = (await db.execute(select(SiteCabinetUser).where(
        SiteCabinetUser.company_id == cid, SiteCabinetUser.email == addr,
    ))).scalar_one_or_none()
    if row is None or not row.is_active:
        return {"email": addr, "level": "guest", "known": False,
                "company": None, "counterpartyId": None, "demos": []}
    client = None
    if row.counterparty_id:
        client = (await db.execute(select(Counterparty).where(
            Counterparty.id == row.counterparty_id))).scalar_one_or_none()
    # Дверь в собственный контур клиента. Пока стек разворачивается, адреса не
    # отдаём: кнопка, ведущая в недоделанное, хуже отсутствующей кнопки.
    space = None
    if row.counterparty_id:
        space_row = (await db.execute(select(ClientSpace).where(
            ClientSpace.company_id == cid,
            ClientSpace.counterparty_id == row.counterparty_id,
            ClientSpace.status == "active",
        ))).scalars().first()
        if space_row and space_row.domain:
            space = {"domain": space_row.domain, "slug": space_row.slug}
    return {
        "email": addr, "level": row.level, "known": True,
        "company": client.short_name or client.name if client else None,
        "counterpartyId": str(row.counterparty_id) if row.counterparty_id else None,
        "inn": client.inn if client else None,
        # Пусто = все стенды: у сайта это звёздочка, форму ответа держим общей.
        "demos": list(row.demos or []),
        "space": space,
    }


@router.get("/pull/demos")
async def pull_demos(
    x_space_token: str | None = Header(None, alias="X-Space-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Каталог стендов для витрины кабинета. Выключенные не отдаём вовсе."""
    cid = await _pull_company(db, x_space_token)
    res = await db.execute(select(SiteDemo).where(
        SiteDemo.company_id == cid, SiteDemo.is_enabled.is_(True),
    ).order_by(SiteDemo.sort, SiteDemo.title))
    return {"items": [{
        "id": r.code, "title": r.title, "desc": r.description or "",
        "upstream": r.upstream_url or "", "external": r.external_url or "",
        "landing": r.landing or "",
    } for r in res.scalars().all()]}


# ── Пространства клиентов ────────────────────────────────────────────────────
# У кого какой контур и в каком он состоянии. Кабинет спрашивает адрес отсюда:
# контур принадлежит клиенту, а не сайту.


class ClientSpaceIn(BaseModel):
    counterparty_id: str
    slug: str
    domain: str = ""
    status: str = "planned"
    note: str | None = None


SPACE_STATUSES = {"planned", "deploying", "active", "suspended"}


def _space_card(row: ClientSpace, client: Counterparty | None) -> dict[str, Any]:
    return {
        "id": str(row.id), "slug": row.slug, "domain": row.domain,
        "status": row.status, "note": row.note,
        "counterpartyId": str(row.counterparty_id),
        "counterpartyName": client.short_name or client.name if client else None,
    }


@router.get("/client-spaces")
async def client_spaces(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """У кого развёрнуто пространство и в каком оно состоянии."""
    cid = await assert_company_product(company_id, user, db, "site")
    res = await db.execute(
        select(ClientSpace, Counterparty)
        .outerjoin(Counterparty, Counterparty.id == ClientSpace.counterparty_id)
        .where(ClientSpace.company_id == cid).order_by(ClientSpace.slug)
    )
    return {"items": [_space_card(row, client) for row, client in res.all()]}


@router.post("/client-spaces")
async def client_space_save(
    payload: ClientSpaceIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Записать пространство клиента. Ключ — код стека: он же имя каталога поставки."""
    cid = await assert_company_product(company_id, user, db, "site")
    slug = payload.slug.strip().lower()
    if not slug:
        raise HTTPException(400, "Нужен код стека")
    if payload.status not in SPACE_STATUSES:
        raise HTTPException(400, f"Неизвестное состояние: {payload.status}")

    row = (await db.execute(select(ClientSpace).where(
        ClientSpace.company_id == cid, ClientSpace.slug == slug))).scalar_one_or_none()
    if row is None:
        row = ClientSpace(company_id=cid, slug=slug)
        db.add(row)
    row.counterparty_id = uuid.UUID(payload.counterparty_id)
    row.domain = payload.domain.strip()
    row.status = payload.status
    row.note = payload.note
    await db.commit()
    await db.refresh(row)
    client = (await db.execute(select(Counterparty).where(
        Counterparty.id == row.counterparty_id))).scalar_one_or_none()
    return _space_card(row, client)


# ── Гостевая переписка ───────────────────────────────────────────────────────
# Написавший из кабинета — такой же обратившийся, как позвонивший. Поэтому своего
# движка переписки нет: сообщение уходит в Поддержку тредом канала `web`, и оператор
# видит его в общей очереди. Ядро здесь посредник: у сайта один собеседник —
# пространство, у пространства — своя Поддержка.


class GuestMessageIn(BaseModel):
    email: str
    body: str
    name: str | None = None


async def _support_call(
    db: AsyncSession, cid: uuid.UUID, method: str, path: str,
    *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Служебный вызов Поддержки от имени пространства."""
    try:
        app_row, link, token = await space_projection._target(db, cid, "support")
    except space_projection.ProjectionError as e:
        raise HTTPException(503, str(e)) from e
    url = f"{space_projection._internal_base_url(app_row, 'support')}{path}"
    body = dict(json_body or {})
    query_params = dict(params or {})
    if method == "POST":
        body["companyId"] = link.external_company_id
    else:
        query_params["companyId"] = link.external_company_id
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.request(
            method, url, params=query_params or None, json=body if method == "POST" else None,
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, space_projection._error_text(resp))
    return resp.json()


@router.post("/push/message")
async def push_message(
    payload: GuestMessageIn,
    x_space_token: str | None = Header(None, alias="X-Space-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Гость написал из кабинета — кладём в очередь Поддержки."""
    cid = await _pull_company(db, x_space_token)
    text = payload.body.strip()
    if not text:
        raise HTTPException(400, "Пустое сообщение")
    return await _support_call(db, cid, "POST", "/api/v1/eco/inbox/web", json_body={
        "email": payload.email.strip().lower(), "name": payload.name, "body": text,
    })


@router.get("/pull/thread")
async def pull_thread(
    email: str = Query(...),
    x_space_token: str | None = Header(None, alias="X-Space-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Лента переписки для кабинета: что человек писал и что ему ответили."""
    cid = await _pull_company(db, x_space_token)
    try:
        return await _support_call(db, cid, "GET", "/api/v1/eco/inbox/web",
                                   params={"email": email.strip().lower()})
    except HTTPException as e:
        # Поддержки в стеке может не быть вовсе — тогда переписки просто нет,
        # и кабинет покажет форму обращения, а не ошибку.
        if e.status_code == 503:
            return {"threadId": None, "messages": [], "reason": e.detail}
        raise
