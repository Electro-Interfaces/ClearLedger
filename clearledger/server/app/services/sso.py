"""Платформенный SSO ElsyPlus — Ledger как временный провайдер идентичности.

Ledger подписывает короткоживущий RS256-JWT (iss=elsyplus, kid=elsyplus/1),
другое приложение экосистемы (Support/Координатор) проверяет его публичным ключом
через JWKS — без общего секрета. Прецедент — `services/jitsi.py` (Ledger уже
подписывает RS256 для prosody). На Фазе 1/2 роль провайдера переедет на Zitadel;
контракт (JWKS + клеймы) forward-совместим.

⚠ handoff-токен короткоживущий (5 мин) и служит ТОЛЬКО для входа в целевое
приложение: оно проверяет подпись/срок/aud, матчит пользователя по sub/email и
поднимает СВОЮ сессию. Долгоживущие права — в целевом приложении, не в этом токене.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import jwt

from app.config import get_settings

settings = get_settings()


def _private_key() -> str | None:
    b64 = settings.sso_signing_key
    if not b64:
        return None
    return base64.b64decode(b64).decode("utf-8")


def sso_apps() -> list[dict[str, str]]:
    """Каталог приложений экосистемы из конфига (Фаза 0).

    Строка env: `code|Название|https://base|/callback|icon`, записи через «;».
    Пустой callback → `/sso/callback`."""
    out: list[dict[str, str]] = []
    for row in (settings.sso_apps or "").split(";"):
        parts = [p.strip() for p in row.split("|")]
        if len(parts) >= 3 and parts[0] and parts[2]:
            out.append({
                "code": parts[0],
                "name": parts[1] or parts[0],
                "base_url": parts[2].rstrip("/"),
                "callback": (parts[3] if len(parts) > 3 and parts[3] else "/sso/callback"),
                "icon": parts[4] if len(parts) > 4 else "",
            })
    return out


def find_app(code: str) -> dict[str, str] | None:
    return next((a for a in sso_apps() if a["code"] == code), None)


def sign_sso_token(*, user, company_id, companies: list[dict[str, Any]], aud: str) -> str | None:
    """RS256 handoff-токен для приложения-аудитории `aud`. None, если SSO выключен."""
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": settings.sso_issuer,
        "aud": aud,
        "sub": str(user.id),
        "email": user.email,
        "name": getattr(user, "name", None),
        "cid": str(company_id) if company_id else None,  # текущая компания
        "companies": companies,                          # [{id, slug, role}]
        "iat": now,
        "nbf": now - 10,
        "exp": now + settings.sso_token_ttl_seconds,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.sso_kid})


def public_jwks() -> dict[str, Any]:
    """Публичный JWKS: верификаторы проверяют токены по kid, не зная приватный ключ."""
    key = _private_key()
    if not key:
        return {"keys": []}
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from jwt.algorithms import RSAAlgorithm

    priv = load_pem_private_key(key.encode("utf-8"), password=None)
    jwk = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update({"kid": settings.sso_kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}
