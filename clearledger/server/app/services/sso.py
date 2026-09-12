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

    Строка env: `code|Название|https://base|/callback|icon|mode|layer`, записи через «;».
    Пустой callback → `/sso/callback`.

    `mode` — как открывается приложение:
      * `sso`  (по умолчанию) — выпускаем handoff-токен, приложение принимает его на callback;
      * `link` — **мост**: приложение о нашем токене не знает (общий Plane/Jitsi Фазы 0),
        открываем просто по ссылке. Мост живёт и при выключенном SSO — иначе лаунчер
        молчал бы там, где ходить уже есть куда.

    `layer` — слой рабочего стола экосистемы (docs/CORE.md §2):
      * `service` — универсальный сервис контейнера (Заявки/Конференции/Чат): один на всю
        экосистему, потребляется всеми приложениями;
      * `app` (по умолчанию) — приложение экосистемы (Support)."""
    out: list[dict[str, str]] = []
    for row in (settings.sso_apps or "").split(";"):
        parts = [p.strip() for p in row.split("|")]
        if len(parts) >= 3 and parts[0] and parts[2]:
            mode = parts[5].lower() if len(parts) > 5 and parts[5] else "sso"
            layer = parts[6].lower() if len(parts) > 6 and parts[6] else "app"
            out.append({
                "code": parts[0],
                "name": parts[1] or parts[0],
                "base_url": parts[2].rstrip("/"),
                "callback": (parts[3] if len(parts) > 3 and parts[3] else "/sso/callback"),
                "icon": parts[4] if len(parts) > 4 else "",
                "mode": mode if mode in ("sso", "link") else "sso",
                "layer": layer if layer in ("service", "app") else "app",
            })
    return out


def launcher_apps() -> list[dict[str, str]]:
    """Что реально показывать в лаунчере: мосты — всегда, handoff — только с ключом SSO."""
    return [a for a in sso_apps() if a["mode"] == "link" or settings.sso_enabled]


def find_app(code: str) -> dict[str, str] | None:
    return next((a for a in sso_apps() if a["code"] == code), None)


def sign_sso_token(*, user, company_id, companies: list[dict[str, Any]], aud: str) -> str | None:
    """RS256 handoff-токен для приложения-аудитории `aud`. None, если SSO выключен."""
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    cid = str(company_id) if company_id else None
    # `adm` — администратор экосистемы-контейнера (суперадмин либо admin в текущей компании).
    # Нужен рельсу приложения: рисовать ли переход в Центр управления. Правами НЕ является —
    # доступ проверяет само Ядро, приложение по клейму только показывает кнопку.
    is_admin = bool(getattr(user, "is_superadmin", False)) or any(
        c.get("id") == cid and c.get("role") == "admin" for c in companies
    )
    payload = {
        "iss": settings.sso_issuer,
        "aud": aud,
        "sub": str(user.id),
        "email": user.email,
        "name": getattr(user, "name", None),
        "cid": cid,                                      # текущая компания
        "adm": is_admin,                                 # админ контейнера (для рельса приложения)
        "companies": companies,                          # [{id, slug, role}]
        "iat": now,
        "nbf": now - 10,
        "exp": now + settings.sso_token_ttl_seconds,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.sso_kid})


def sign_visit_token(*, user, space_code: str, self_code: str,
                     ttl_seconds: int = 120) -> str | None:
    """Пропуск нашего сотрудника в пространство партнёра.

    Не handoff: тот выпускается ДЛЯ приложения внутри своего контура и проверяется
    нашим же ключом. Здесь пропуск читает чужое Ядро — оно берёт наш публичный ключ
    по адресу из своей записи о нас и по нему решает, пускать ли.

    Аудитория — код принимающего пространства: пропуск, выписанный к одному
    клиенту, не должен открывать дверь к другому.
    """
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": settings.sso_issuer,
        "aud": f"space:{space_code}",
        "sub": str(user.id),
        "email": user.email,
        "name": getattr(user, "name", None),
        # Откуда пришёл: по этому коду принимающая сторона находит свою запись о
        # нас и проверяет, что связь включена и не отозвана.
        "space": self_code,
        "iat": now,
        "nbf": now - 10,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.sso_kid})


def sign_vendor_token(*, user, company_id: str, self_code: str, vendor_code: str,
                      operation: str, demo_id: str | None = None) -> str | None:
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    return jwt.encode({
        "iss": settings.sso_issuer, "aud": f"vendor:{vendor_code}",
        "sub": str(user.id), "email": user.email, "company_id": company_id,
        "space": self_code, "operation": operation, "demo_id": demo_id,
        "iat": now, "nbf": now - 10, "exp": now + 120,
    }, key, algorithm="RS256", headers={"kid": settings.sso_kid})


def sign_service_token(*, aud: str, scope: str, ttl_seconds: int = 120,
                       company_id: str | None = None, actor_id: str | None = None) -> str | None:
    """Служебный (машинный) токен Ядра для приложения `aud`.

    Отличается от handoff-токена клеймом `svc`: он не про человека, а про право
    выполнить операцию между системами (например проекцию общих сущностей). Живёт
    минуты — ровно на время вызова. None, если ключ подписи не настроен.
    """
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": settings.sso_issuer,
        "aud": aud,
        "sub": f"service:{scope}",
        "svc": scope,
        "iat": now,
        "nbf": now - 10,
        "exp": now + ttl_seconds,
    }
    if company_id is not None:
        payload["cid"] = company_id
    if actor_id is not None:
        payload["actor"] = actor_id
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
