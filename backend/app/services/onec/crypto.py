"""Шифрование паролей 1С (Fernet)."""

from cryptography.fernet import Fernet

from app.config import settings

# Ключ шифрования — первые 32 байта SECRET_KEY в base64
# Fernet требует url-safe base64 ключ 32 байта
import base64
import hashlib


def _get_fernet() -> Fernet:
    """Создаёт Fernet из SECRET_KEY приложения."""
    key_bytes = hashlib.sha256(settings.secret_key.encode()).digest()
    key_b64 = base64.urlsafe_b64encode(key_bytes)
    return Fernet(key_b64)


def encrypt_password(plain: str) -> str:
    """Шифрует пароль для хранения в БД."""
    f = _get_fernet()
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Расшифровывает пароль из БД."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()
