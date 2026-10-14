"""Одноразовые коды входа (TOTP, RFC 6238) — второй фактор (аудит 07.10.2026).

Утёкший пароль без телефона владельца больше не даёт входа. Алгоритм — на стандартной
библиотеке: HMAC-SHA1, шаг 30 секунд, 6 цифр — так работают Google Authenticator,
Яндекс Ключ, Microsoft Authenticator. Допускаем соседние шаги (±30 с) на разъехавшиеся
часы телефона. Секрет в базе — зашифрованным (тот же Fernet-ключ, что у паролей 1С).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    """Секрет в base32 (20 байт) — его вводят в приложение-аутентификатор."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    """Код верен для текущего шага или соседних (±window). Сравнение за постоянное время."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return False
    counter = int((at if at is not None else time.time()) // STEP)
    return any(hmac.compare_digest(_code(secret, counter + d), code) for d in range(-window, window + 1))


def uri(secret: str, email: str, issuer: str) -> str:
    """Ссылка otpauth:// — приложение-аутентификатор заводит запись по ней."""
    return (f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def seal(secret: str) -> str:
    from app.services.onec.crypto import encrypt_password
    return encrypt_password(secret)


def unseal(sealed: str | None) -> str:
    if not sealed:
        return ""
    from app.services.onec.crypto import decrypt_password
    return decrypt_password(sealed)


if __name__ == "__main__":  # контрольные значения RFC 6238 (SHA1, 8 цифр → младшие 6)
    rfc = base64.b32encode(b"12345678901234567890").decode()
    for t, expected in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert _code(rfc, int(t // STEP)) == expected, (t, _code(rfc, int(t // STEP)))
        assert verify(rfc, expected, at=t)
    assert not verify(rfc, "000000", at=59)
    print("ok")
