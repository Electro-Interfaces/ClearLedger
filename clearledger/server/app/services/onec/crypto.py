from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    """Fernet-ключ, выведенный из SECRET_KEY через SHA-256.

    SECRET_KEY уже хранится в .env и используется для JWT. Этого же
    секрета достаточно для симметричного шифрования паролей подключений
    к 1С — отдельный ключ не нужен. При ротации SECRET_KEY все
    зашифрованные пароли становятся недействительными — это сознательное
    поведение, эквивалентное инвалидации JWT-токенов.
    """
    settings = get_settings()
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_password(plain: str) -> str:
    if not plain:
        raise ValueError("Пароль не может быть пустым")
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    if not token:
        raise ValueError("Зашифрованный пароль не может быть пустым")
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
