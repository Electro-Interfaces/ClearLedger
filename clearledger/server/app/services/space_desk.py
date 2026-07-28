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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (AccountingDoc, ChargeSession, Company, CompanyRole, Connector,
                        Contract, CorporateClient, Counterparty, EzsEquipmentUnit, EzsProject,
                        EzsSite, HubexTask, InfoArticle, MatrixGroupRoom, MetrikaConnection,
                        ServiceLocation, SourceFile, User, UserCompany)

WINDOW_DAYS = 30
ONLINE_WINDOW_MINUTES = 6
# Стадии проекта, на которых работа идёт (остальные — закрытые и архив).
LIVE_PROJECT_STAGES = ("lead", "screening", "negotiation", "decision",
                       "contracting", "construction", "commissioning")
# Заявка HubEx считается закрытой по названию статуса — справочник статусов ведёт
# сама HubEx, поэтому сверяем по подстроке, а не по коду.
CLOSED_TASK_MARKERS = ("закрыт", "выполнен", "отменен", "отменён")


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
        "sales": await _sales(db, company_id, since),
        "corp": await _corp(db, company_id),
        "marketing": await _marketing(db, company_id),
        "support": await _support(db, company_id),
        "finance": await _finance(db, company_id),
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
    total = await _count(db, Connector, cid)
    active = await _count(db, Connector, cid, Connector.status == "active")
    # Загрузки за окно — по файлам приёмки: «когда последний раз приезжали данные».
    files = int((await db.execute(
        select(func.count()).select_from(SourceFile)
        .where(SourceFile.company_id == cid, SourceFile.created_at >= since)
    )).scalar() or 0)
    return {"metrics": [
        _m("коннекторов", f"{_n(active)}/{_n(total)}", "ok" if active else "warn"),
        _m(f"загрузок за {WINDOW_DAYS} дн", _n(files), None if files else "warn"),
    ]}


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


async def _sales(db: AsyncSession, cid: uuid.UUID, since: datetime) -> dict[str, Any]:
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


async def _corp(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    clients = await _count(db, CorporateClient, cid)
    return {"metrics": [_m("юрлиц в базе", _n(clients))] if clients else []}


async def _marketing(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    connected = await _count(db, MetrikaConnection, cid, MetrikaConnection.enabled.is_(True))
    return {"metrics": [
        _m("Яндекс.Метрика", "подключена" if connected else "не подключена",
           "ok" if connected else "warn"),
    ]}


async def _support(db: AsyncSession, cid: uuid.UUID) -> dict[str, Any]:
    total = await _count(db, HubexTask, cid)
    if not total:
        return {"metrics": []}
    closed_filter = [func.lower(func.coalesce(HubexTask.status, "")).not_like(f"%{m}%")
                     for m in CLOSED_TASK_MARKERS]
    open_tasks = await _count(db, HubexTask, cid, *closed_filter)
    return {"metrics": [
        _m("заявок всего", _n(total)),
        _m("в работе", _n(open_tasks), "warn" if open_tasks else "ok"),
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
