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

from app.models import App, AppModule, Company, CompanyApp, CompanyAppModule

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
# Разделы «Управления» — такие же модули, как у любого приложения. Благодаря этому роль
# может дать доступ к части администрирования: например бухгалтеру — только «Объекты» и
# «Справочники», без людей и ролей. Раньше «Управление» было хардкод-плиткой «для админов
# компании», и промежуточных прав не существовало вовсе.
# Свои сотрудники и люди компаний-партнёров — РАЗНЫЕ разделы, а не один список с
# пометкой: вопросы у них разные («кому что можно внутри организации» против «какая
# сторонняя компания допущена и до чего»), и доступ к ним выдаётся по отдельности.
_ADMIN_MODULES: list[tuple[str, str]] = [
    ("members", "Сотрудники"), ("partners", "Компании"), ("roles", "Роли и доступ"),
    ("apps", "Приложения"), ("objects", "Объекты"), ("refs", "Справочники"),
    ("notify", "Оповещения"), ("connections", "Подключения"),
    ("map", "Карта"), ("profile", "Реквизиты"), ("invites", "Приглашения"),
    ("audit", "Журнал"),
]

_APPS: list[dict[str, Any]] = [
    {"code": "admin", "name": "Управление", "icon": "shield-check", "sort": 5,
     "desc": "Администрирование пространства: люди, доступы, объекты, аудит",
     "modules": _ADMIN_MODULES},
    {"code": "ledger", "name": "Учёт", "icon": "book-open", "sort": 10,
     "desc": "Учёт, аналитика, сверка", "modules": _LEDGER_MODULES},
    # Продукты, выделенные ИЗ Учёта (решение МАГа 26.07.2026): режем по рабочим местам,
    # а не по видам учёта. Для сети ЭЗС разрез идёт по жизни объекта: строим → эксплуатируем
    # → продаём → чиним → считаем; «Данные» — служебная кухня сбора. Все живут в том же SPA
    # (маршруты в sso_router.INTERNAL_ROUTES), поэтому base_url им не нужен.
    {"code": "projects", "name": "Проекты", "icon": "hard-hat", "sort": 12,
     "desc": "Стройка сети: подбор площадок, портфель проектов, присоединение, ввод",
     "modules": []},
    {"code": "ops", "name": "Эксплуатация", "icon": "gauge", "sort": 14,
     "desc": "Состояние сети, баланс, парк оборудования, склады и ЗИП", "modules": []},
    # Имя по делу, а не по владению: здесь ПРОДАЮТ. «Сеть» заняли группой разделов
    # внутри продукта, «Реализация» — термин бухучёта, он живёт в Финансах.
    {"code": "sales", "name": "Продажи", "icon": "bar-chart-3", "sort": 16,
     "desc": "Коммерция сети: сессии, надёжность, динамика и сегментация", "modules": []},
    # Работа с юрлицами — своё рабочее место: договоры, тарифные планы, лимиты и счета
    # ведёт не тот человек, который смотрит загрузку сети.
    {"code": "corp", "name": "Корпоративный процессинг", "icon": "building-2", "sort": 17,
     "desc": "Юрлица: договоры, тарифные планы, корпоративные и частные клиенты",
     "modules": []},
    {"code": "shop", "name": "Интернет-магазин", "icon": "shopping-cart", "sort": 18,
     "desc": "Товары, витрина и заказы: сопутка и общепит на объектах", "modules": []},
    {"code": "marketing", "name": "Маркетинг", "icon": "megaphone", "sort": 19,
     "desc": "Поведение клиентов, сегментация сети и веб-аналитика", "modules": []},
    {"code": "finance", "name": "Финансы", "icon": "wallet", "sort": 25,
     "desc": "Бухгалтерский и налоговый учёт, первичка, контрагенты, выгрузка",
     "modules": []},
    {"code": "data", "name": "Данные", "icon": "database", "sort": 60,
     "desc": "Откуда берутся цифры: коннекторы, загрузка, нормализация, разрезы",
     "modules": []},
    {"code": "support", "name": "Поддержка", "icon": "life-buoy", "sort": 20,
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
        else:
            # Каталог в коде — источник истины: подтягиваем и переименования (снимает
            # старые брендовые префиксы «РусГидро Учёт» → «Учёт»), и порядок с иконкой.
            # Раньше обновлялось только имя, поэтому смена sort в коде до стенда не доезжала.
            for field, value in (("name", name), ("icon", a.get("icon")),
                                 ("sort", a.get("sort", 100)), ("description", a.get("desc"))):
                if value is not None and getattr(app, field) != value:
                    setattr(app, field, value); changed = True
        for i, (mc, mn) in enumerate(a["modules"]):
            ex = (await db.execute(select(AppModule).where(
                AppModule.app_id == app.id, AppModule.code == mc))).scalar_one_or_none()
            if ex is None:
                db.add(AppModule(app_id=app.id, code=mc, name=mn, sort=(i + 1) * 10,
                                 is_core=(mc == "management")))
                changed = True
            else:
                # Каталог в коде — источник истины и для ИМЕН модулей, не только приложений.
                # Иначе переименование раздела доезжает до меню, но не до матрицы прав, и в
                # двух местах интерфейса один раздел зовётся по-разному (так «Компании»
                # остались «Партнёрами» после первого деплоя).
                if ex.name != mn:
                    ex.name = mn
                    changed = True
                if ex.sort != (i + 1) * 10:
                    ex.sort = (i + 1) * 10
                    changed = True
    if changed:
        await db.commit()


# Продукты, на которые разрезан Учёт (см. фронтовую карту `config/spaceProducts.ts`).
# Разрез включён у профиля `energy`: там разделы Учёта разошлись по рабочим местам, и сам
# «Учёт» плиткой больше не показывается. У топливного профиля разреза нет — Учёт единый.
_CARVED_PRODUCTS = {"projects", "ops", "sales", "corp", "shop", "marketing", "finance", "data"}
_CARVED_PROFILE = "energy"
# Всегда: управление пространством + универсальные продукты (чаты, заявки, конференции).
_ALWAYS_ON = {"admin", "chat", "plan", "conf"}


def _default_app_on(code: str, profile_id: str | None = None) -> bool:
    """Что подключено компании без явной настройки.

    Управление и универсальные продукты — сразу: без «Управления» пространством нельзя
    распоряжаться вообще. Прикладные приложения со своим контуром и данными (Координатор)
    подключаются осознанно.

    Остальное зависит от профиля: у сети ЭЗС (`energy`) работают продукты разреза, у
    топливного профиля — единый «Учёт». Плитка продукта, которого в профиле нет, вела бы
    в пустой раздел, поэтому дефолты разведены, а не сложены.
    """
    if code in _ALWAYS_ON:
        return True
    carved = profile_id == _CARVED_PROFILE
    if code in _CARVED_PRODUCTS:
        return carved
    if code == "ledger":
        return not carved
    return False


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
    # Профиль компании решает дефолт для профильных продуктов (см. _default_app_on).
    profile_id = (await db.execute(
        select(Company.profile_id).where(Company.id == company_id))).scalar_one_or_none()

    out: list[dict[str, Any]] = []
    for app in apps:
        rec = ca.get(app.id)
        enabled = rec.enabled if rec is not None else _default_app_on(app.code, profile_id)
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
