"""Показатели продуктов для рабочего стола пространства.

Стол отвечал только на вопрос «куда войти»: одинаковые плитки, за которыми могло
стоять и рабочее место с боевыми данными, и пустая заготовка. Администратору нужен
другой ответ — «что здесь живёт»: сколько людей, объектов, сессий, заявок, когда
последний раз приезжали данные. Поэтому стол получает по каждому продукту два-три
показателя из его собственного контура.

Правила:
- **дёшево**: только COUNT/SUM по индексированным колонкам, никаких выборок строк —
  стол открывается первым экраном и не должен ждать аналитику;
- **честно**: показываем то, что реально лежит в базе этой компании. Ноль — это тоже
  ответ («данные ещё не грузили»), поэтому нули не прячем;
- **пусто, если нечего сказать**: у мостов (Заявки, Конференции) своих данных в Ядре
  нет, у незаполненных продуктов — тоже; такие карточки остаются без цифр, и это
  видно.

Продукты, которых нет у профиля компании, сюда не попадают: стол показывает только
подключённые (`/api/sso/apps`), а сводка отдаёт словарь по коду продукта.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (AccountingDoc, App, AppCompanyLink, CbMovementDoc, CbNomenclature,
                        Channel, ChargeSession, Company,
                        CompanyRole, Contract, CorporateClient, Counterparty, EzsEquipmentUnit,
                        FuelShift, FuelShiftSale, StockOnHand,
                        EzsProject, EzsSite, InfoArticle, MarketObservation, MarketSite,
                        MatrixGroupRoom, MetrikaConnection, ServiceLocation, SourceFile, User,
                        UserCompany)
from app.services import sso
from app.services.space_projection import _internal_base_url

WINDOW_DAYS = 30
ONLINE_WINDOW_MINUTES = 6
# Стол не должен ждать приложение, которое молчит: без цифр карточка переживёт, а
# крутящийся первый экран — нет.
APP_TIMEOUT = httpx.Timeout(3.0)
# Активная воронка проекта (`services/sitesService.ts` FUNNEL_STAGES без «В эксплуатации»);
# «Заморожен» и «Архив» в работу не считаем — по ним никто сегодня не действует.
LIVE_PROJECT_STAGES = ("lead", "screening", "negotiation", "dd", "decision",
                       "contracting", "construction", "commissioning")


async def desk_summary(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Показатели по коду продукта: {"sales": {"metrics": [...]}, ...}."""
    company = await db.get(Company, company_id)
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    online_since = datetime.now(timezone.utc) - timedelta(minutes=ONLINE_WINDOW_MINUTES)

    products: dict[str, Any] = {
        "admin": await _admin(db, company_id, online_since),
        "data": await _data(db, company_id, since),
        "info": await _info(db, company_id),
        "chat": await _chat(db, company_id),
        "projects": await _projects(db, company_id),
        "ops": await _ops(db, company_id),
        "sales": await _sales(db, company_id, since, getattr(company, "profile_id", None)),
        "shop": await _shop(db, company_id),
        "corp": await _corp(db, company_id),
        "marketing": await _marketing(db, company_id),
        "support": await _support(db, company_id),
        "finance": await _finance(db, company_id),
        "pulse": await _pulse(db, company_id),
    }
    return {
        "windowDays": WINDOW_DAYS,
        "profileId": getattr(company, "profile_id", None),
        "products": {code: p for code, p in products.items() if p["metrics"]},
    }


def _m(label: str, value: str, tone: str | None = None) -> dict[str, Any]:
    """Показатель: короткая подпись + значение. tone красит значение (ok|warn|bad)."""
    return {"label": label, "value": value, "tone": tone}


def _n(value: int | float | None) -> str:
    """Целое с разделителем тысяч — узкий пробел, как в остальном интерфейсе."""
    return f"{int(value or 0):,}".replace(",", " ")


def _short_money(value: float | None) -> str:
    """Деньги коротко: 1,2 млн ₽ / 940 тыс ₽ — в плитку длинное число не влезает."""
    v = float(value or 0)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + " млн ₽"
    if v >= 1_000:
        return f"{v / 1_000:.0f} тыс ₽"
    return f"{v:.0f} ₽"


async def _count(db: AsyncSession, model, company_id: uuid.UUID, *where) -> int:
    q = select(func.count()).select_from(model).where(model.company_id == company_id, *where)
    return int((await db.execute(q)).scalar() or 0)


async def _pulse(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    """«Пульс» на столе отвечает на свой же вопрос: нужно ли вмешательство сегодня.

    Считает ТЕМ ЖЕ кодом, что и экран дня: второй набор правил разошёлся бы с
    первым за неделю, и плитка начала бы врать про то, что за ней.
    """
    from app.routers.pulse_router import pulse_day_data

    try:
        data = await pulse_day_data(db, str(cid))
    except Exception:  # noqa: BLE001 — одна плитка не должна ронять весь стол
        return {"metrics": []}
    n = len(data["cards"])
    stale = data["stale_days"]
    return {"metrics": [
        _m("требуют внимания", _n(n), "warn" if n else "ok"),
        _m("данные сети",
           "нет" if stale is None else ("сегодня" if stale <= 0 else f"{stale} дн назад"),
           "warn" if (stale is None or stale > 7) else "ok"),
    ]}


async def _admin(db: AsyncSession, cid: uuid.UUID, online_since: datetime) -> dict[str, Any]:
    people = await _count(db, UserCompany, cid)
    online = int((await db.execute(
        select(func.count()).select_from(UserCompany)
        .join(User, User.id == UserCompany.user_id)
        .where(UserCompany.company_id == cid, User.last_seen_at.is_not(None),
               User.last_seen_at >= online_since)
    )).scalar() or 0)
    roles = await _count(db, CompanyRole, cid)
    return {"metrics": [
        _m("человек", _n(people)),
        _m("в сети", _n(online), "ok" if online else None),
        _m("ролей", _n(roles)),
    ]}


async def _data(db: AsyncSession, cid: uuid.UUID, since: datetime) -> dict[str, Any]:
    # Считаем КАНАЛЫ, а не `connectors`: живая цепочка приёма — Источник → Канал → Разрез,
    # старая таблица коннекторов у разрезанного профиля пустая и врала бы нулём.
    channels = await _count(db, Channel, cid)
    row = (await db.execute(
        select(func.count(), func.max(SourceFile.created_at))
        .where(SourceFile.company_id == cid, SourceFile.created_at >= since)
    )).first()
    files, last_at = (row or (0, None))
    return {"metrics": [
        _m("каналов приёма", _n(channels), "ok" if channels else "warn"),
        _m(f"загрузок за {WINDOW_DAYS} дн", _n(files), None if files else "warn"),
        _m("последняя", *_freshness(last_at)),
    ]}


def _freshness(last_at: datetime | None) -> tuple[str, str | None]:
    """Свежесть данных словами: «сегодня» важнее даты — по ней видно, живой ли приём."""
    if last_at is None:
        return "нет", "warn"
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - last_at).days
    if days <= 0:
        return "сегодня", "ok"
    if days == 1:
        return "вчера", "ok"
    return f"{days} дн назад", "warn" if days > 7 else None


async def _info(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    # Статьи бывают общие (company_id IS NULL) и компанийские — человек видит и те, и те.
    articles = int((await db.execute(
        select(func.count()).select_from(InfoArticle)
        .where((InfoArticle.company_id == cid) | (InfoArticle.company_id.is_(None)))
    )).scalar() or 0)
    return {"metrics": [_m("материалов", _n(articles), None if articles else "warn")]}


async def _chat(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    rooms = await _count(db, MatrixGroupRoom, cid)
    return {"metrics": [_m("каналов", _n(rooms))]}


async def _projects(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    sites = await _count(db, EzsSite, cid)
    if not sites:
        return {"metrics": []}
    live = await _count(db, EzsProject, cid, EzsProject.stage.in_(LIVE_PROJECT_STAGES))
    done = await _count(db, EzsProject, cid, EzsProject.stage == "live")
    return {"metrics": [
        _m("площадок", _n(sites)),
        _m("в работе", _n(live), "ok" if live else None),
        _m("введено", _n(done)),
    ]}


async def _ops(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    objects = await _count(db, ServiceLocation, cid)
    if not objects:
        return {"metrics": []}
    equipment = await _count(db, EzsEquipmentUnit, cid)
    return {"metrics": [
        _m("объектов", _n(objects)),
        _m("единиц железа", _n(equipment)),
    ]}


async def _sales(db: AsyncSession, cid: uuid.UUID, since: datetime,
                 profile_id: str | None = None) -> dict[str, Any]:
    """Продажи: у сети ЭЗС это зарядные сессии, у розницы нефтепродуктов — смены АЗС.

    Продукт один и тот же, но торгуют компании разным: у ГИГ зарядных сессий нет вовсе,
    и карточка стояла бы пустой при 23 тысячах продаж по сменам.
    """
    if profile_id == "fuel":
        return await _fuel_sales(db, cid, since)
    # naive-датой лежит время МСК — сравниваем без tz, как везде в аналитике сессий.
    since_naive = since.replace(tzinfo=None)
    row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(ChargeSession.amount), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since_naive)
    )).first()
    sessions, energy, amount = (row or (0, 0, 0))
    if not sessions:
        return {"metrics": []}
    return {"metrics": [
        _m(f"сессий за {WINDOW_DAYS} дн", _n(sessions)),
        _m("кВтч", _n(energy)),
        _m("выручка", _short_money(float(amount))),
    ]}


async def _fuel_sales(db: AsyncSession, cid: uuid.UUID, since: datetime) -> dict[str, Any]:
    """Топливо за окно: закрытые смены, литры и выручка. Дата — у смены, не у продажи."""
    shifts = select(FuelShift.id).where(
        FuelShift.company_id == cid, FuelShift.closed_at >= since)
    row = (await db.execute(
        select(func.count(func.distinct(FuelShiftSale.shift_id)),
               func.coalesce(func.sum(FuelShiftSale.liters), 0),
               func.coalesce(func.sum(FuelShiftSale.amount), 0))
        .where(FuelShiftSale.company_id == cid, FuelShiftSale.shift_id.in_(shifts))
    )).first()
    shift_count, liters, amount = (row or (0, 0, 0))
    if not shift_count:
        return {"metrics": []}
    return {"metrics": [
        _m(f"смен за {WINDOW_DAYS} дн", _n(shift_count)),
        _m("литров", _n(liters)),
        _m("выручка", _short_money(float(amount))),
    ]}


async def _shop(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    """Магазин: сопутка и общепит. Товарный контур живёт остатками и движением, а не
    окном в 30 дней — документы приходят из ЦБ пачками, и «за месяц» врало бы в дни
    между выгрузками."""
    items = await _count(db, CbNomenclature, cid)
    if not items:
        return {"metrics": []}
    stock = (await db.execute(
        select(func.coalesce(func.sum(StockOnHand.quantity * StockOnHand.retail_price), 0))
        .where(StockOnHand.company_id == cid)
    )).scalar() or 0
    docs = await _count(db, CbMovementDoc, cid)
    return {"metrics": [
        _m("позиций в номенклатуре", _n(items)),
        _m("остаток в ценах продажи", _short_money(float(stock))),
        _m("документов движения", _n(docs)),
    ]}


async def _corp(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    clients = await _count(db, CorporateClient, cid)
    return {"metrics": [_m("юрлиц в базе", _n(clients))] if clients else []}


async def _marketing(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    """Рынок вокруг сети: сколько чужого мы видим и насколько свежо (docs/MARKET.md)."""
    sites = await _count(db, MarketSite, cid, MarketSite.status != "closed")
    rivals = await _count(db, MarketSite, cid, MarketSite.status != "closed",
                          MarketSite.kind == "ezs", MarketSite.location_id.is_(None))
    last_obs = (await db.execute(
        select(func.max(MarketObservation.observed_on))
        .where(MarketObservation.company_id == cid))).scalar()
    if not sites:
        # Рынок пуст — честно говорим об этом состоянием подключения Метрики, а не нулями.
        connected = await _count(db, MetrikaConnection, cid, MetrikaConnection.enabled.is_(True))
        return {"metrics": [
            _m("точек рынка", "0", "warn"),
            _m("Яндекс.Метрика", "подключена" if connected else "нет",
               "ok" if connected else "warn"),
        ]}
    return {"metrics": [
        _m("точек рынка", _n(sites)),
        _m("чужих ЭЗС", _n(rivals), "warn" if rivals else None),
        _m("наблюдение", last_obs or "нет", None if last_obs else "warn"),
    ]}


async def _support(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    """Заявки Координатора.

    Своей базы у Ядра тут нет: заявки живут в приложении, поэтому спрашиваем его тем же
    служебным каналом, что и проекцию (RS256-токен, внутренний адрес). Приложение молчит
    или старой версии — карточка останется без цифр, но стол не сломается.
    """
    row = (await db.execute(
        select(App, AppCompanyLink)
        .join(AppCompanyLink, AppCompanyLink.app_id == App.id)
        .where(AppCompanyLink.company_id == cid, App.code == "support")
    )).first()
    if row is None:
        return {"metrics": []}
    app_row, link = row
    token = sso.sign_service_token(aud="support", scope="projection")
    if not token:
        return {"metrics": []}
    url = f"{_internal_base_url(app_row, 'support')}/api/v1/eco/summary"
    try:
        async with httpx.AsyncClient(timeout=APP_TIMEOUT) as client:
            resp = await client.get(url, params={"companyId": link.external_company_id},
                                    headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            return {"metrics": []}
        tickets = (resp.json() or {}).get("tickets") or {}
    except (httpx.HTTPError, ValueError):
        return {"metrics": []}

    total = int(tickets.get("total") or 0)
    if not total:
        return {"metrics": []}
    open_tasks = int(tickets.get("open") or 0)
    fresh = int(tickets.get("fresh") or 0)
    return {"metrics": [
        _m("заявок всего", _n(total)),
        _m("в работе", _n(open_tasks), "warn" if open_tasks else "ok"),
        _m("новых", _n(fresh), "warn" if fresh else None),
    ]}


async def _finance(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    docs = await _count(db, AccountingDoc, cid)
    contracts = await _count(db, Contract, cid)
    parties = await _count(db, Counterparty, cid)
    return {"metrics": [
        _m("документов", _n(docs)),
        _m("договоров", _n(contracts)),
        _m("контрагентов", _n(parties)),
    ]}
