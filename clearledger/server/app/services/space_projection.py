"""Проекция общих сущностей пространства в приложения-разрезы (docs/SPACE.md §6).

Приложение ведёт свои таблицы и переписывать его ради первого шага дорого, поэтому Ядро
не заставляет его читать реестр, а САМО отправляет туда карточки: «вот объекты этой
компании». Направление одно — из Ядра в приложение; обратная запись не предусмотрена,
иначе появляется второй мастер и вопрос, чья правда.

Ключ отправки — карта соответствия компаний (`eco_app_company_links`): без пары
«наша компания → его компания» проекция невозможна. Это то, что не даёт в
мультикомпанийном контейнере отправить объекты одной компании в пространство другой.

Транспорт: HTTP-вызов приложения со служебным токеном Ядра (RS256, клейм svc=projection),
который приложение проверяет по тому же JWKS, что и единый вход. Общих секретов нет.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, AppCompanyLink, ServiceLocation, User, UserCompany
from app.services import space_registry, sso

# Куда приложение принимает проекцию. Путь фиксирован контрактом; адрес приложения
# берётся из реестра (App.base_url), а не из хардкода.
SYNC_PATHS = {"support": "/api/v1/eco/objects/sync"}
USER_SYNC_PATHS = {"support": "/api/v1/eco/users/sync"}
DEFAULT_TIMEOUT = 30.0

# Роль в компании (пространство) → роль в приложении. Задаётся на приложение в реестре
# (`App.config.roleMap`), здесь — разумный дефолт для Координатора: администратор остаётся
# администратором, остальные видят заявки своей компании.
DEFAULT_ROLE_MAP = {"support": {"admin": "admin", "user": "company"}}


class ProjectionError(RuntimeError):
    pass


async def project_objects(
    db: AsyncSession, company_id: uuid.UUID, app_code: str,
) -> dict[str, Any]:
    """Отправить объекты компании в приложение. Идемпотентно — повтор ничего не дублирует."""
    app_row = (await db.execute(select(App).where(App.code == app_code))).scalar_one_or_none()
    if app_row is None:
        raise ProjectionError(f"Приложение не найдено в реестре: {app_code}")

    path = SYNC_PATHS.get(app_code)
    if not path:
        raise ProjectionError(f"Приложение «{app_code}» не умеет принимать проекцию объектов")

    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app_row.id,
        AppCompanyLink.company_id == company_id))).scalar_one_or_none()
    if link is None:
        raise ProjectionError(
            "Нет соответствия компаний: задайте, какой компании приложения отвечает эта "
            "компания пространства (Центр управления → Приложения)")

    base = _internal_base_url(app_row, app_code)
    token = sso.sign_service_token(aud=app_code, scope="projection")
    if not token:
        raise ProjectionError("Единый вход не настроен (нет ключа подписи) — проекция невозможна")

    objects = await _objects_payload(db, company_id)

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{base}{path}",
                json={"companyId": link.external_company_id, "objects": objects},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e

    if resp.status_code >= 400:
        detail = _error_text(resp)
        raise ProjectionError(f"Приложение отклонило проекцию (HTTP {resp.status_code}): {detail}")

    result = resp.json()
    return {
        "app": app_code,
        "companyId": str(company_id),
        "externalCompanyId": link.external_company_id,
        "sent": len(objects),
        "created": result.get("created", 0),
        "updated": result.get("updated", 0),
        "skipped": result.get("skipped", []),
    }


async def project_users(
    db: AsyncSession, company_id: uuid.UUID, app_code: str,
) -> dict[str, Any]:
    """Отправить людей компании в приложение: заведён в пространстве — есть в разрезе.

    Пароли НЕ передаются. Вход в приложение — через единый вход Ядра; локальный пароль
    там не нужен, а гонять хеши между системами — лишний риск. У кого пароль в приложении
    уже был (ручной перенос), тот его сохраняет: проекция обновляет имя, роль и
    активность, но не трогает учётные данные.
    """
    app_row = (await db.execute(select(App).where(App.code == app_code))).scalar_one_or_none()
    if app_row is None:
        raise ProjectionError(f"Приложение не найдено в реестре: {app_code}")

    path = USER_SYNC_PATHS.get(app_code)
    if not path:
        raise ProjectionError(f"Приложение «{app_code}» не умеет принимать проекцию людей")

    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app_row.id,
        AppCompanyLink.company_id == company_id))).scalar_one_or_none()
    if link is None:
        raise ProjectionError(
            "Нет соответствия компаний: задайте, какой компании приложения отвечает эта "
            "компания пространства")

    token = sso.sign_service_token(aud=app_code, scope="projection")
    if not token:
        raise ProjectionError("Единый вход не настроен (нет ключа подписи) — проекция невозможна")

    users = await _users_payload(db, company_id, app_row, app_code)

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{_internal_base_url(app_row, app_code)}{path}",
                json={"companyId": link.external_company_id, "users": users},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e

    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение отклонило проекцию (HTTP {resp.status_code}): {_error_text(resp)}")

    result = resp.json()
    return {
        "app": app_code,
        "companyId": str(company_id),
        "sent": len(users),
        "created": result.get("created", 0),
        "updated": result.get("updated", 0),
        "skipped": result.get("skipped", []),
    }


async def _users_payload(
    db: AsyncSession, company_id: uuid.UUID, app_row: App, app_code: str,
) -> list[dict[str, Any]]:
    """Люди компании с ролью, переведённой в термины приложения."""
    cfg = app_row.config or {}
    role_map = cfg.get("roleMap") or DEFAULT_ROLE_MAP.get(app_code, {})
    default_role = cfg.get("defaultRole") or role_map.get("user") or "customer"

    rows = (await db.execute(
        select(User, UserCompany)
        .join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == company_id)
        .order_by(User.email)
    )).all()

    out: list[dict[str, Any]] = []
    for user, membership in rows:
        space_role = "admin" if (user.is_superadmin or membership.role == "admin") else membership.role
        out.append({
            "email": user.email,
            "name": user.name or user.email,
            "role": role_map.get(space_role, default_role),
            "spaceRole": space_role,
            "isActive": True,
        })
    return out


async def _objects_payload(db: AsyncSession, company_id: uuid.UUID) -> list[dict[str, Any]]:
    """Паспорта объектов компании — ровно то, что общее (без прикладных атрибутов)."""
    res = await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company_id)
        .order_by(ServiceLocation.code))
    return [space_registry.to_card(l) for l in res.scalars().all()]


def _internal_base_url(app_row: App, app_code: str) -> str:
    """Адрес приложения ВНУТРИ стека.

    Наружный адрес (`https://<domain>/support`) для машинного вызова не годится: запрос
    ушёл бы из контейнера в интернет и вернулся через кромку. Поэтому используем
    внутреннее имя сервиса, если оно задано в конфигурации приложения реестра.
    """
    cfg = app_row.config or {}
    internal = cfg.get("internalUrl") or cfg.get("internal_url")
    if internal:
        return str(internal).rstrip("/")
    # Соглашение стека: имя docker-сервиса совпадает с кодом приложения.
    default_ports = {"support": 3003}
    port = default_ports.get(app_code)
    return f"http://{app_code}:{port}" if port else f"http://{app_code}"


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error") or data.get("detail") or data)[:300]
    except Exception:
        return resp.text[:300]
