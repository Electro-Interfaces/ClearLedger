"""SSO ElsyPlus — лаунчер приложений, handoff-токен и JWKS.

Фаза 0 единой экосистемы: Ledger — временный провайдер идентичности (см.
`services/sso.py`). `/sso/authorize` вызывается ФРОНТОМ Ledger (bearer из
localStorage), а НЕ браузерным редиректом — при редиректе токен не долетел бы.
Фронт получает URL с токеном и делает переход сам.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.deps import scope_company_id
from app.models import Company, User, UserCompany
from app.services import sso

settings = get_settings()
router = APIRouter(prefix="/sso", tags=["SSO ElsyPlus"])

# Внутренние продукты пространства: живут в этом же SPA, поэтому открываются маршрутом,
# а не handoff-токеном и не ссылкой на чужой домен. Манифеста у них нет — источник истины
# реестр (`eco_apps`), здесь только соответствие «продукт → маршрут».
INTERNAL_ROUTES = {"admin": "/admin", "ledger": "/workspace", "chat": "/messages",
                   # «Пульс» — рабочее место руководителя (ecosystem-deploy/docs/PULSE.md).
                   "pulse": "/pulse",
                   # Продукты разреза Учёта (см. app_registry._CARVED_PRODUCTS и
                   # фронтовую карту config/spaceProducts.ts — маршруты обязаны совпадать).
                   "projects": "/projects", "ops": "/operations", "sales": "/sales",
                   "corp": "/corporate", "shop": "/shop", "marketing": "/marketing",
                   "finance": "/finance", "data": "/data", "info": "/info",
                   "connect": "/connect",
                   # «Задачи»: свой движок в Ядре — типы с маршрутами, переадресация,
                   # сроки (решение МАГа 06.08.2026, docs/TASKS.md). Витрина заявок
                   # Поддержки осталась на /tickets — её открывают из «Пульса»,
                   # Центра управления и карточки объекта, продуктом она больше не числится.
                   "plan": "/tasks",
                   # «Дело» — документооборот пространства.
                   "docs": "/docs",
                   # «Сайт» — публичная витрина и кабинет клиента (elsyplus.ru).
                   "site": "/site",
                   # Продукты в подключении: маршрут есть, за ним заставка.
                   "netlink": "/netlink", "accounting": "/accounting", "diag": "/diagnostics",
                   # Рабочие места компании без объектов (профиль `office`): бухгалтерия-
                   # эталон и «Реализация» (товары и услуги — её разделы). Маршруты обязаны
                   # совпадать с фронтовой картой `config/spaceProducts.ts` — сверяет тест.
                   "books": "/books", "revenue": "/revenue", "econ": "/economy",
                   # «Периметр» — обязательства и имущество вне баланса, все три слоя.
                   "perimeter": "/perimeter",
                   # Аудитор: панель сквозная (шапка и правый док), а плитка ведёт на
                   # его страницу — каталог навыков и разговор во всю ширину.
                   "auditor": "/auditor"}
# Слой рабочего стола: управление пространством и служебная кухня стоят отдельно от
# прикладных продуктов. «Данные» — служебное: ошибка там ломает все продукты сразу.
INTERNAL_LAYERS = {"admin": "admin", "data": "admin", "info": "admin", "connect": "admin",
                   "chat": "service", "plan": "service",
                   # «Дело» — сервис контейнера, как чаты и конференции:
                   # документооборот нужен любому приложению пространства,
                   # а не только тому, кто ведёт сеть или учёт.
                   "docs": "service",
                   "pulse": "app",
                   "ledger": "app", "projects": "app", "ops": "app",
                   "sales": "app", "corp": "app", "shop": "app", "marketing": "app",
                   "finance": "app", "netlink": "app", "accounting": "app", "diag": "admin",
                   # Аудитор — сервис контейнера, как чат: не рабочее место с витринами,
                   # а способ спросить про то, что уже открыто в других продуктах.
                   "books": "app", "revenue": "app", "auditor": "service",
                   # «Сайт» — рабочее место, а не служебная кухня: витрину и кабинет
                   # ведёт человек по своему делу, как бухгалтерию или реализацию.
                   "site": "app"}
# Порядок в списке: сначала управление, потом приложения, сервисы — в конце.
INTERNAL_SORT = {"admin": 5, "pulse": 8, "ledger": 10, "projects": 12, "ops": 14, "sales": 16,
                 "corp": 17, "shop": 18, "marketing": 19, "support": 20, "netlink": 22,
                 "finance": 25, "accounting": 26,
                 "books": 20, "revenue": 21,
                 "chat": 30, "auditor": 31, "docs": 32, "site": 33,
                 "plan": 40, "conf": 50, "connect": 59, "data": 60,
                 "diag": 61, "info": 62}


@router.get("/apps")
async def list_apps(
    company_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Каталог ВСЕХ продуктов пространства — для стола, лаунчера и рельса.

    Раньше каталог собирался только из манифестов внешних приложений, поэтому внутренние
    продукты (Управление, Чаты, Учёт) в списке приложений не появлялись — их приходилось
    рисовать хардкодом в каждом месте. Теперь список один, а `mode` говорит, КАК открывать:

      * `internal` — маршрут этого же SPA (`route`): Управление, Чаты, Учёт;
      * `sso`      — переход по handoff-токену (Координатор);
      * `link`     — согласованный мост на своём домене (Заявки, Конференции).

    `chat_enabled` — включён ли движок чата в стеке (Matrix); `allowed_apps` — коды,
    доступные роли (null = без ограничений).
    """
    apps = sso.launcher_apps()

    # Компания в запросе не обязательна: лаунчер и рельс её не передают. Тогда берём
    # выбранную в интерфейсе (заголовок X-Company-Id) — иначе список продуктов в шапке
    # отличался бы от списка на столе, что и случилось: «Управление» было только на столе.
    if not company_id:
        try:
            company_id = str(await scope_company_id(user, db))
        except HTTPException:
            company_id = None

    # Реестр решает, что подключено компании: отключённый в «Управлении» продукт не
    # должен появляться на столе. Раньше реестр гейтил только внутренние модули Ledger,
    # а мосты (Заявки, Конференции) показывались всегда — выключить их было нечем.
    chat_enabled = settings.chat_enabled
    if company_id:
        from app.services import app_registry
        try:
            reg_cid = uuid.UUID(company_id)
        except (ValueError, TypeError):
            reg_cid = None
        if reg_cid is not None:
            reg_apps = await app_registry.company_apps(db, reg_cid)
            registry = {a["code"]: a["enabled"] for a in reg_apps}
            apps = [a for a in apps if registry.get(a["code"], True)]
            chat_enabled = chat_enabled and registry.get("chat", True)
            # Описание из реестра — и мостам тоже. Раньше оно доезжало только до внутренних
            # продуктов, поэтому плитки внешних объясняли лишь способ входа («Открывается
            # по ссылке»), а что за продуктом стоит — нет. У «Конференций» так терялось
            # главное: встреча идёт в браузере и участнику не нужна регистрация.
            desc_by_code = {a["code"]: (a.get("description") or "") for a in reg_apps}
            for a in apps:
                if not a.get("description"):
                    a["description"] = desc_by_code.get(a["code"], "")
            # Внутренние продукты пространства — из реестра: у них нет манифеста, потому
            # что жить им негде, кроме этого же SPA. Чат добавляем только если движок
            # поднят в стеке: плитка без Matrix вела бы в пустоту.
            for reg in reg_apps:
                code = reg["code"]
                route = INTERNAL_ROUTES.get(code)
                if route is None or not reg["enabled"]:
                    continue
                if code == "chat" and not chat_enabled:
                    continue
                apps.append({
                    "code": code, "name": reg["name"], "base_url": "", "callback": "",
                    "icon": reg.get("icon") or "", "mode": "internal",
                    "layer": INTERNAL_LAYERS.get(code, "app"), "route": route,
                    "description": reg.get("description") or "",
                })
            apps.sort(key=lambda a: INTERNAL_SORT.get(a["code"], 100))

    allowed: list[str] | None = None
    if company_id and not user.is_superadmin:
        from app.services import app_registry
        try:
            cid = uuid.UUID(company_id)
        except (ValueError, TypeError):
            cid = None
        if cid is not None:
            uc = (await db.execute(select(UserCompany).where(
                UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
            # Админ компании видит всё; иначе — ЭФФЕКТИВНЫЕ права членства.
            # ⚠ Именно `resolve_member_modules`, а не `uc.modules`: при назначении
            # ИМЕНОВАННОЙ роли в членстве стоит `role_id`, а `modules` остаётся NULL.
            # Читая поле напрямую, стол считал такого человека полнодоступным и
            # показывал все плитки — назначенная роль не действовала вообще.
            if uc is None:
                # Не член компании — и не админ платформы: показывать нечего. Раньше
                # здесь оставалось `allowed = None`, то есть «без ограничений», и
                # посторонний получал полный каталог пространства.
                allowed, apps = [], []
            elif uc.role != "admin":
                from app.auth import resolve_member_modules
                allowed = sorted(await app_registry.effective_apps(
                    db, cid, await resolve_member_modules(uc, db)))
                apps = [a for a in apps if a["code"] in allowed]

    return {
        "enabled": bool(apps) or chat_enabled,
        "sso_enabled": settings.sso_enabled,
        "chat_enabled": chat_enabled,
        "apps": apps,
        "allowed_apps": allowed,
    }


@router.get("/authorize")
async def authorize(
    app: str = Query(..., description="код приложения-получателя"),
    company_id: str | None = Query(None, description="компания контекста (по умолчанию текущая)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Выпустить handoff-токен для приложения `app` и вернуть URL перехода.

    Токен короткоживущий (RS256, ~5 мин), целевое приложение проверит его по JWKS.
    Приложения-мосты (`mode=link`) токена не получают — только адрес.
    """
    target = sso.find_app(app)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Неизвестное приложение: {app}")

    # Мост (Фаза 0): приложение вне нашего контура идентичности — открываем по ссылке,
    # без токена. Свой вход оно спросит само.
    if target["mode"] == "link":
        return {"url": target["base_url"], "app": app, "mode": "link", "expires_in": 0}

    if not settings.sso_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "SSO не настроен (нет ключа подписи)")

    rows = (await db.execute(
        select(UserCompany, Company)
        .join(Company, Company.id == UserCompany.company_id)
        .where(UserCompany.user_id == user.id)
    )).all()
    companies = [{"id": str(c.id), "slug": c.slug, "role": uc.role} for uc, c in rows]
    cid = company_id or (str(user.company_id) if user.company_id
                         else (companies[0]["id"] if companies else None))

    token = sso.sign_sso_token(user=user, company_id=cid, companies=companies, aud=app)
    url = f"{target['base_url']}{target['callback']}#token={token}"
    # Переход в приложение — часть истории активности человека: без этой записи журнал
    # знает только вход в Ядро, а «когда заходил в Координатор» ответить нечем.
    if cid is not None:
        await log_audit(db, actor=user, company_id=uuid.UUID(cid),
                        action="sso.handoff", target=app)
        await db.commit()
    return {"url": url, "app": app, "mode": "sso", "expires_in": settings.sso_token_ttl_seconds}


@router.get("/jwks.json")
async def jwks() -> dict[str, Any]:
    """Публичный JWKS — приложения экосистемы проверяют токены по kid."""
    return sso.public_jwks()
