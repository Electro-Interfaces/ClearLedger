"""Текущая личность приложения: Ядро владеет допуском, приложение — своей историей."""
from __future__ import annotations
import hashlib
import json
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from app.auth import _named_key, assert_company_product
from app.models import App, AppCompanyLink, Company, User, UserCompany, CompanyRole
from app.services.app_roles import app_roles
from app.services.app_registry import company_apps

SCOPE = "support.identity"

async def identity_company(db, raw_key: str):
    key = await _named_key(raw_key or "", db)
    if key is None or key.station_id is not None or SCOPE not in (key.scopes or []):
        raise HTTPException(403, "Нет права проверки личности приложения")
    return key.company_id

async def resolve_support_identity(db, raw_key: str, subject: uuid.UUID) -> dict:
    return await support_identity(db, await identity_company(db, raw_key), subject)

async def support_identity(db, company_id: uuid.UUID, subject: uuid.UUID) -> dict:
    company = await db.get(Company, company_id)
    user = await db.get(User, subject)
    member = await db.get(UserCompany, (subject, company_id))
    # locked_until ограничивает новый парольный вход, а не отзывает действующие
    # сеансы Ядра. Для отзыва используем членство и token_version, как остальные API.
    if company is None or user is None or member is None or user.mail_only:
        raise HTTPException(403, "Нет действующего доступа к пространству")
    await assert_company_product(str(company_id), user, db, "support")
    if not any(a["code"] == "support" and a["enabled"] for a in await company_apps(db, company_id)):
        raise HTTPException(403, "Приложение не подключено компании")
    link = (await db.execute(select(AppCompanyLink).join(App, App.id == AppCompanyLink.app_id)
            .where(App.code == "support", AppCompanyLink.company_id == company_id))).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "Компания приложения не сопоставлена")
    # Не расширяем ограниченную область Ядра до всей сети в старых API Поддержки.
    # Такие профили требуют отдельного сквозного object/organization ACL.
    if not (user.is_superadmin or member.role == "admin") and (member.object_scope or member.own_organization_id):
        raise HTTPException(403, "Ограниченная область требует сопоставления в приложении")
    roles = await app_roles(db, user, company_id, "support")
    if len(roles) != 1:
        raise HTTPException(403, "Не назначена роль приложения")
    profile = await db.get(CompanyRole, member.role_id) if member.role_id else None
    state = {"user": str(user.id), "company": str(company_id), "tv": user.token_version or 0,
             "roles": roles, "superadmin": user.is_superadmin, "memberRole": member.role,
             "modules": member.modules, "profile": str(member.role_id) if member.role_id else None,
             "profileModules": profile.modules if profile else None,
             "objectScope": member.object_scope, "organization": str(member.own_organization_id) if member.own_organization_id else None}
    version = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return {"subject": str(user.id), "companyId": str(company_id), "companySlug": company.slug,
            "supportCompanyId": link.external_company_id, "name": user.name or user.email, "email": user.email,
            "role": roles[0], "tokenVersion": user.token_version or 0, "authorizationVersion": version,
            "spaceAdmin": bool(user.is_superadmin or member.role == "admin"), "platformAdmin": bool(user.is_superadmin)}


def sign_identity(identity: dict, nonce: str, kind: str = "principal") -> str:
    import time
    import jwt
    from app.services import sso
    key = sso._private_key()
    if not key:
        raise HTTPException(503, "Подпись Ядра недоступна")
    now = int(time.time())
    return jwt.encode({"iss": sso.settings.sso_issuer, "aud": "support-identity",
                       "sub": "service:support.identity", "svc": "support.identity",
                       "iat": now, "nbf": now - 5, "exp": now + 15,
                       "nonce": nonce, "kind": kind, "identity": identity},
                      key, algorithm="RS256", headers={"kid": sso.settings.sso_kid})


async def support_directory(db, raw_key: str) -> dict:
    cid = await identity_company(db, raw_key)
    company = await db.get(Company, cid)
    link = (await db.execute(select(AppCompanyLink).join(App, App.id == AppCompanyLink.app_id)
            .where(App.code == "support", AppCompanyLink.company_id == cid))).scalar_one_or_none()
    if company is None or link is None:
        raise HTTPException(403, "Компания приложения не сопоставлена")
    users = (await db.execute(select(User).join(UserCompany, UserCompany.user_id == User.id)
             .where(UserCompany.company_id == cid).order_by(User.id))).scalars().all()
    if len(users) > 2000:
        raise HTTPException(503, "Каталог требует постраничной синхронизации")
    rows = []
    for user in users:
        try:
            identity = await support_identity(db, cid, user.id)
            role, active = identity["role"], True
        except HTTPException as error:
            if error.status_code != 403:
                raise
            roles = await app_roles(db, user, cid, "support")
            role, active = (roles[0] if len(roles) == 1 else "company"), False
        rows.append({"ecoUserId": str(user.id), "email": user.email, "name": user.name or user.email,
                     "role": role, "isActive": active})
    return {"companyId": str(cid), "supportCompanyId": link.external_company_id,
            "companySlug": company.slug, "complete": True, "users": rows}
