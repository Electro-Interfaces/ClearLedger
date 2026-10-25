"""Роль человека в приложении — для клейма `roles` в токенах Ядра (Я-10).

Раньше в handoff-токене роли приложения не было: приложение видело только роль
в пространстве (`companies[].role` — admin или user) и роль в своей базе, которая
приезжает проекцией (`space_projection`). «Телефонии» базы с людьми негде
держать — данные живут в узле у заказчика, — поэтому роль должна ехать в самом
токене.

Правило то же, что у проекции людей, чтобы приложение получало одну и ту же
роль обоими путями: личное назначение в членстве (`user_companies.app_roles`),
затем роль доступа (`company_roles.app_roles`), затем карта «роль в пространстве →
роль в приложении». У «Телефонии» роль одна — `admin` (решение МАГа 16.10.2026,
ContactHub docs/node-data-api.html §6): её получает администратор компании или
тот, кому её назначили явно. Суперадмин платформы получает `admin` в выбранной
компании (решение МАГа 19.10.2026). Выдающий токен маршрут проверяет существование
компании и подключение продукта; узел проверяет компанию, подпись и аудит доступа.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, CompanyRole, User, UserCompany

# Карты по приложениям; для остальных — карта проекции (space_projection.DEFAULT_ROLE_MAP).
VOICE_ROLE_MAP = {"admin": "admin"}
VOICE_ROLES = {"admin"}


async def app_roles(db: AsyncSession, user: User, company_id: uuid.UUID | str | None,
                    app_code: str) -> list[str]:
    """Роли человека в приложении `app_code` в компании. Пусто — роли нет."""
    from app.services.space_projection import DEFAULT_ROLE_MAP

    if not company_id:
        return []
    try:
        cid = uuid.UUID(str(company_id))
    except ValueError:
        return []
    # Полномочия платформы не зависят от наличия личного членства в компании.
    if app_code == "voice" and user.is_superadmin:
        return ["admin"]
    m = await db.get(UserCompany, (user.id, cid))
    if m is None:
        return []
    access_role = await db.get(CompanyRole, m.role_id) if m.role_id else None
    named = ((m.app_roles or {}).get(app_code)
             or (getattr(access_role, "app_roles", None) or {}).get(app_code))
    if app_code == "voice":
        role = named or VOICE_ROLE_MAP.get(m.role)
        return [role] if role in VOICE_ROLES else []
    # Как в проекции людей (space_projection._users_payload): карта из реестра
    # приложения, без неё — карта по умолчанию, затем роль по умолчанию.
    space_role = "admin" if (user.is_superadmin or m.role == "admin") else m.role
    cfg = (await db.execute(select(App.config).where(App.code == app_code))).scalar_one_or_none() or {}
    role_map = cfg.get("roleMap") or DEFAULT_ROLE_MAP.get(app_code, {})
    role = named or role_map.get(space_role) or cfg.get("defaultRole") or role_map.get("user")
    return [role] if role else []
