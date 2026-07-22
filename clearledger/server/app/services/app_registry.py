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
_APPS: list[dict[str, Any]] = [
    {"code": "ledger", "name": "ElsyPlus Ledger", "icon": "book-open", "sort": 10,
     "desc": "Учёт, аналитика, сверка", "modules": _LEDGER_MODULES},
    {"code": "support", "name": "ElsyPlus Support / Координатор", "icon": "life-buoy", "sort": 20,
     "base_url": "https://support.dataworker.ru", "desc": "Заявки, journey, поддержка", "modules": []},
]


async def seed_apps(db: AsyncSession) -> None:
    """Идемпотентно завести каталог приложений/модулей (вызывается при старте)."""
    changed = False
    for a in _APPS:
        app = (await db.execute(select(App).where(App.code == a["code"]))).scalar_one_or_none()
        if app is None:
            app = App(code=a["code"], name=a["name"], description=a.get("desc"),
                      base_url=a.get("base_url"), icon=a.get("icon"), sort=a.get("sort", 100))
            db.add(app); await db.flush(); changed = True
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
    """Ledger подключён у всех по умолчанию; прочие приложения — по явному включению."""
    return code == "ledger"


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
