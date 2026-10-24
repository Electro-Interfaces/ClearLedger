"""Scoped RS256 access: endpoint-specific, pinned keys, grants on BOTH sides."""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member
from app.models import User, UserCompany
from app.services.management_config import Kind, ManagementConfig, OutboundGrant, RemoteSource
from app.services.service_accounts import is_service_account

TOKEN_TTL = 60
SCOPE = "management:read"
TOKEN_TYPE = "management+jwt"


def _key(encoded: str) -> bytes:
    return base64.b64decode(encoded, validate=True)


def sign_access(config: ManagementConfig, source: RemoteSource, grant: OutboundGrant,
                kind: Kind) -> str:
    now = int(time.time())
    return jwt.encode({
        "iss": config.code, "aud": f"management:{source.code}",
        "sub": str(grant.local_user_id), "actor_company_id": str(grant.local_company_id),
        "target_user_id": str(grant.remote_user_id), "target_company_id": str(source.company_id),
        "grant_id": grant.id, "kind": kind, "scope": SCOPE,
        "iat": now, "nbf": now, "exp": now + TOKEN_TTL, "jti": uuid.uuid4().hex,
    }, _key(config.signing_private_key_b64), algorithm="RS256", headers={"typ": TOKEN_TYPE})


@dataclass(frozen=True)
class DelegatedActor:
    user: User
    company_id: uuid.UUID


async def verify_access(token: str, kind: Kind, config: ManagementConfig,
                        db: AsyncSession) -> DelegatedActor:
    denied = HTTPException(403, "Источник недоступен для этого пользователя")
    if not config.enabled or len(token) > 16384:
        raise denied
    try:
        # Непроверенный iss служит ТОЛЬКО индексом в локальном allowlist.
        issuer_code = jwt.decode(token, options={"verify_signature": False}).get("iss")
        issuer = next((i for i in config.trusted_issuers if i.issuer == issuer_code), None)
        if issuer is None or jwt.get_unverified_header(token).get("typ") != TOKEN_TYPE:
            raise denied
        claims = jwt.decode(token, _key(issuer.public_key_b64), algorithms=["RS256"],
                            audience=f"management:{config.code}", issuer=issuer.issuer,
                            options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti",
                                                 "actor_company_id", "target_user_id",
                                                 "target_company_id", "grant_id", "scope", "kind"],
                                     "strict_aud": True})
        if (claims["scope"] != SCOPE or claims["kind"] != kind
                or type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or type(claims["nbf"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= TOKEN_TTL
                or claims["nbf"] != claims["iat"]):
            raise denied
        grant = next((g for g in issuer.grants if g.id == claims["grant_id"]), None)
        if (grant is None or kind not in grant.kinds
                or claims["sub"] != str(grant.actor_user_id)
                or claims["actor_company_id"] != str(grant.actor_company_id)
                or claims["target_user_id"] != str(grant.user_id)
                or claims["target_company_id"] != str(grant.company_id)):
            raise denied
        user = await db.get(User, grant.user_id)
        # Делегирование не создаёт учётки/членства и не оживляет mail-only/робота.
        if user is None or user.mail_only or is_service_account(user):
            raise denied
        # Даже у superadmin привязка компании должна быть явной и отзываться.
        if await db.get(UserCompany, (user.id, grant.company_id)) is None:
            raise denied
        await assert_company_member(str(grant.company_id), user, db)
        return DelegatedActor(user=user, company_id=grant.company_id)
    except HTTPException:
        raise denied
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, StopIteration):
        raise denied
