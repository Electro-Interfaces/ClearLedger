"""Подпись Jitsi-JWT (RS256 / ASAP) для видеоконференций TradeLedger.

meet.dataworker.ru работает с per-issuer JWT: TradeLedger подписывает организаторский
токен СВОИМ приватным ключом (iss=ledger, kid=ledger/1), prosody проверяет публичным
ключом с keyserver по kid (`asap_key_server/<sha256_hex(kid)>.pem`). Приватный ключ —
env `JITSI_SIGNING_KEY` (PEM в base64), НЕ в git; публичный лежит на keyserver; `ledger`
должен быть в `JWT_ACCEPTED_ISSUERS` Jitsi-стека.
"""
import base64
import secrets
import time
from urllib.parse import quote

import jwt

from app.config import get_settings

settings = get_settings()


def _private_key() -> str | None:
    b64 = settings.jitsi_signing_key
    if not b64:
        return None
    return base64.b64decode(b64).decode("utf-8")


def new_room() -> str:
    """Случайная неугадываемая комната."""
    return f"ledger-{secrets.token_hex(8)}"


def sign_token(room: str, display_name: str, *, moderator: bool = True, hours: int = 4) -> str | None:
    """Подписать RS256 JWT организатора. None, если ключ подписи не задан."""
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": settings.jitsi_issuer,
        "aud": "jitsi",
        "sub": settings.jitsi_xmpp_domain,  # внутренний XMPP-домен, не публичный URL
        "room": room,
        "iat": now,
        "nbf": now - 10,
        "exp": now + hours * 3600,
        "context": {"user": {"name": display_name or "Пользователь", "moderator": moderator}},
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.jitsi_kid})


def meeting_urls(room: str, display_name: str, hours: int = 4) -> dict:
    """Модераторская (с токеном) + гостевая (без токена) ссылки на комнату."""
    token = sign_token(room, display_name, moderator=True, hours=hours)
    base = f"https://{settings.jitsi_domain}/{quote(room)}"
    return {
        "room": room,
        "moderator_url": f"{base}?jwt={token}" if token else base,
        "guest_url": base,
    }
