"""ElsyPlus Core — серверный реестр приложений/модулей на компанию.

Единый источник «что подключено компании» — замена клиентского localStorage-демо
(`moduleConnectionService`). Питает лаунчер приложений (SSO), админку «Приложения»
и (следующим шагом) гейтинг разделов рабочей области. Эффективное состояние:
явная запись `CompanyApp`/`CompanyAppModule` ИЛИ дефолт (Ledger вкл. у всех,
модуль — по `AppModule.default_on`).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, AppModule, CompanyApp, CompanyAppModule

# Ledger-модули = ключи доступа RBAC (access_catalog.ACCESS_KEYS) — единый словарь.
_LEDGER_MODULES: list[tuple[str, str]] = [
    ("management", "Продажи / Управленческий"), ("store", "Магазин"),
    ("accounting", "Бухгалтерский"), ("financial", "Финансовый"), ("tax", "Налоговый"),
    ("documents", "Документы"), ("reconciliation", "Сверка"), ("sources", "Источники"),
    ("locations", "Объекты"), ("onec", "1С"), ("catalog", "Справочники"),
]
# name — функциональное имя продукта пространства, без брендов. Ни продуктовых
# (Ledger/Support), ни бренда компании: компания названа один раз в шапке, повторять её в
# каждой плитке («РусГидро Учёт», «РусГидро Координатор») — визуальный шум.
_APPS: list[dict[str, Any]] = [
    {"code": "ledger", "name": "Учёт", "icon": "book-open", "sort": 10,
     "desc": "Учёт, аналитика, сверка", "modules": _LEDGER_MODULES},
    {"code": "support", "name": "Координатор", "icon": "life-buoy", "sort": 20,
     "base_url": "https://support.dataworker.ru", "desc": "Заявки, journey, поддержка", "modules": []},
    # Универсальные продукты пространства. В реестре они наравне с остальными: включаются
    # компании, гейтятся ролью, видны в конструкторе доступа. Раньше чат жил хардкодом во
    # фронте, а заявки с конференциями — только в строке каталога SSO, и в реестре их не
    # было вовсе: роль не могла ни дать к ним доступ, ни отобрать.
    {"code": "chat", "name": "Чаты", "icon": "message-circle", "sort": 30,
     "desc": "Переписка и темы в пространстве компании", "modules": []},
    {"code": "plan", "name": "Заявки", "icon": "clipboard-list", "sort": 40,
     "desc": "Задачи и заявки пространства", "modules": []},
    {"code": "conf", "name": "Конференции", "icon": "video", "sort": 50,
     "desc": "Видеовстречи участников пространства", "modules": []},
]


async def seed_apps(db: AsyncSession) -> None:
    """Идемпотентно завести каталог приложений/модулей (вызывается при старте)."""
    # Самозаживление: create_all НЕ добавляет колонки в существующие таблицы. Для уже
    # развёрнутых eco_apps дотягиваем config (иначе запрос поля config упадёт).
    from sqlalchemy import text
    try:
        await db.execute(text("ALTER TABLE eco_apps ADD COLUMN IF NOT EXISTS config JSONB"))
        await db.commit()
    except Exception:  # noqa: BLE001 — не валим старт из-за миграции
        await db.rollback()

    changed = False
    for a in _APPS:
        name = a["name"]
        app = (await db.execute(select(App).where(App.code == a["code"]))).scalar_one_or_none()
        if app is None:
            app = App(code=a["code"], name=name, description=a.get("desc"),
                      base_url=a.get("base_url"), icon=a.get("icon"), sort=a.get("sort", 100))
            db.add(app); await db.flush(); changed = True
        elif app.name != name:
            # Снимает и старые брендовые префиксы («РусГидро Учёт» → «Учёт») у тех,
            # кто был засеян до этого решения.
            app.name = name; changed = True
        for i, (mc, mn) in enumerate(a["modules"]):
            ex = (await db.execute(select(AppModule).where(
                AppModule.app_id == app.id, AppModule.code == mc))).scalar_one_or_none()
            if ex is None:
                db.add(AppModule(app_id=app.id, code=mc, name=mn, sort=(i + 1) * 10,
                                 is_core=(mc == "management")))
                changed = True
    if changed:
        await db.commit()


def _default_app_on(code: str) -> bool:
    """Что подключено новой компании без настройки.

    Учёт и универсальные продукты пространства (чаты, заявки, конференции) — сразу: они
    ничего не стоят и нужны всем. Прикладные приложения вроде Координатора подключаются
    осознанно, потому что за ними стоит отдельный контур и данные.
    """
    return code in {"ledger", "chat", "plan", "conf"}


async def company_apps(db: AsyncSession, company_id) -> list[dict[str, Any]]:
    """Эффективный список приложений компании + модули + признак enabled."""
    apps = (await db.execute(
        select(App).where(App.is_active.is_(True)).order_by(App.sort))).scalars().all()
    ca = {r.app_id: r for r in (await db.execute(
        select(CompanyApp).where(CompanyApp.company_id == company_id))).scalars().all()}
    cam = {(r.app_id, r.module_code): r.enabled for r in (await db.execute(
        select(CompanyAppModule).where(CompanyAppModule.company_id == company_id))).scalars().all()}
    mods: dict[Any, list[AppModule]] = {}
    for m in (await db.execute(select(AppModule).order_by(AppModule.sort))).scalars().all():
        mods.setdefault(m.app_id, []).append(m)

    out: list[dict[str, Any]] = []
    for app in apps:
        rec = ca.get(app.id)
        enabled = rec.enabled if rec is not None else _default_app_on(app.code)
        out.append({
            "id": str(app.id), "code": app.code, "name": app.name,
            "description": app.description, "baseUrl": app.base_url, "icon": app.icon,
            "enabled": enabled,
            "modules": [{
                "code": m.code, "name": m.name, "isCore": m.is_core,
                "enabled": cam.get((app.id, m.code), m.default_on),
            } for m in mods.get(app.id, [])],
        })
    return out


async def access_catalog(db: AsyncSession, company_id) -> list[dict[str, Any]]:
    """Дерево приложений экосистемы для конструктора роли (RBAC): app-ключ + модули
    (`app:module`). Объединяет реестр (Ledger с модулями, Support) и сервисы рабочего
    стола (Чат/Заявки/Конференции), чтобы роль могла давать права на ВСЮ систему, а
    не только на модули Ledger. Показываем лишь подключённое компании."""
    from app.config import get_settings
    from app.services import sso

    tree: list[dict[str, Any]] = []
    for app in await company_apps(db, company_id):
        if not app["enabled"]:
            continue
        tree.append({
            "app": app["code"], "name": app["name"], "icon": app["icon"],
            "modules": [
                {"key": f'{app["code"]}:{m["code"]}', "code": m["code"], "name": m["name"]}
                for m in app["modules"] if m["enabled"]
            ],
        })
    known = {t["app"] for t in tree}

    # Сервисы/приложения стола из каталога SSO (Заявки, Конференции) — без модулей.
    for a in sso.sso_apps():
        if a["code"] not in known:
            tree.append({"app": a["code"], "name": a["name"], "icon": a.get("icon", ""), "modules": []})
            known.add(a["code"])

    # Чат — платформенный сервис (плитка по флагу), тоже гейтится ролью.
    if get_settings().chat_enabled and "chat" not in known:
        tree.append({"app": "chat", "name": "Чат", "icon": "messages-square", "modules": []})

    return tree


async def effective_apps(db: AsyncSession, company_id, modules: list[str] | None) -> set[str]:
    """Коды приложений экосистемы, доступных члену с правами `modules` (роль ∩ реестр):
    приложение из каталога доступно, если его пускает роль (`app_allowed`)."""
    from app.access_catalog import app_allowed
    cat = await access_catalog(db, company_id)
    return {t["app"] for t in cat if app_allowed(modules, t["app"])}


async def set_app(db: AsyncSession, company_id, app_id, enabled: bool) -> None:
    rec = (await db.execute(select(CompanyApp).where(
        CompanyApp.company_id == company_id, CompanyApp.app_id == app_id))).scalar_one_or_none()
    if rec is None:
        db.add(CompanyApp(company_id=company_id, app_id=app_id, enabled=enabled))
    else:
        rec.enabled = enabled
    await db.commit()


async def set_module(db: AsyncSession, company_id, app_id, module_code: str, enabled: bool) -> None:
    rec = (await db.execute(select(CompanyAppModule).where(
        CompanyAppModule.company_id == company_id, CompanyAppModule.app_id == app_id,
        CompanyAppModule.module_code == module_code))).scalar_one_or_none()
    if rec is None:
        db.add(CompanyAppModule(company_id=company_id, app_id=app_id,
                                module_code=module_code, enabled=enabled))
    else:
        rec.enabled = enabled
    await db.commit()


# ── Каталог приложений экосистемы (Ур. 1) — что доступно подключить + настройка ──

async def catalog(db: AsyncSession) -> list[dict[str, Any]]:
    """Полный каталог приложений экосистемы с модулями и конфигурацией (для консоли)."""
    apps = (await db.execute(select(App).order_by(App.sort))).scalars().all()
    mods: dict[Any, list[AppModule]] = {}
    for m in (await db.execute(select(AppModule).order_by(AppModule.sort))).scalars().all():
        mods.setdefault(m.app_id, []).append(m)
    return [{
        "id": str(app.id), "code": app.code, "name": app.name,
        "description": app.description, "baseUrl": app.base_url, "icon": app.icon,
        "kind": app.kind, "isActive": app.is_active, "config": app.config or {},
        "modules": [{
            "code": m.code, "name": m.name, "description": m.description,
            "isCore": m.is_core, "defaultOn": m.default_on,
        } for m in mods.get(app.id, [])],
    } for app in apps]


async def update_app(db: AsyncSession, app_id, *, description=None, base_url=None,
                     config=None, is_active=None) -> bool:
    """Настройка приложения при подключении (описание/адрес/конфиг/активность). None = не менять."""
    app = (await db.execute(select(App).where(App.id == app_id))).scalar_one_or_none()
    if app is None:
        return False
    if description is not None:
        app.description = description
    if base_url is not None:
        app.base_url = base_url
    if config is not None:
        app.config = config
    if is_active is not None:
        app.is_active = is_active
    await db.commit()
    return True
