"""Пароли почтовых ящиков: сотрудник вводит, база хранит под шифром.

Правило поставки «секрет живёт в окружении стека» верно для наших коннекторов —
их настраивает тот, кто разворачивает стек. Но почтовый ящик компании заводит САМ
СОТРУДНИК: он знает адрес и пароль, а доступа к `.env` и права провижинить стек у
него нет и быть не должно. Требовать от него переменную окружения — значит сделать
почту компании зависимой от нас на каждое изменение.

Компромисс: пароль лежит в базе, но зашифрованным ключом стека. Ключ — в окружении
(`MAIL_SECRET_KEY`, иначе выводится из `SECRET_KEY` приложения), поэтому дамп базы
без окружения паролей не выдаёт. Имя переменной окружения (`secret_env`) остаётся
как альтернатива для тех ящиков, что настраивает внедренец.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os

logger = logging.getLogger("clearledger.mail")


def _key() -> bytes:
    """Ключ шифрования: свой для почты, иначе производный от ключа приложения."""
    raw = os.environ.get("MAIL_SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
    if not raw:
        # Пустой ключ — не повод падать при старте: ящики с паролем в базе просто
        # не заработают, и это будет видно в проверке подключения.
        return b""
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def encrypt(password: str) -> str | None:
    key = _key()
    if not key or not password:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key).encrypt(password.encode()).decode()


def decrypt(token: str | None) -> str:
    if not token:
        return ""
    key = _key()
    if not key:
        return ""
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return Fernet(key).decrypt(token.encode()).decode()
    except InvalidToken:
        # Ключ стека сменился — пароль расшифровать нечем. Молча вернуть пустоту
        # правильнее, чем упасть: человек увидит «проверка не прошла» и введёт заново.
        logger.warning("пароль ящика не расшифрован: ключ стека изменился")
        return ""


# Имя переменной окружения приходит из формы ящика, а читаем мы её из окружения
# КОНТЕЙНЕРА. Без ограничения сюда можно было вписать `SECRET_KEY`, `DATABASE_URL`
# или `MAIL_SECRET_KEY`, указать свой IMAP-хост без шифрования — и бэкенд сам
# отправил бы значение наружу командой LOGIN. Поэтому доступны только переменные
# с почтовым префиксом: их заводит внедренец под пароли ящиков.
SECRET_ENV_PREFIX = "MAIL_"
# Служебные переменные почты платформы: имя начинается с MAIL_, но это не пароль
# ящика компании, а ключ шифрования и реквизиты релея приглашений.
SECRET_ENV_DENY = {"MAIL_SECRET_KEY", "MAIL_FROM", "MAIL_RELAYHOST"}


def secret_env_allowed(name: str | None) -> bool:
    """Можно ли брать пароль ящика из этой переменной окружения."""
    if not name:
        return False
    n = name.strip()
    return n.startswith(SECRET_ENV_PREFIX) and n not in SECRET_ENV_DENY


def password_of(account) -> str:
    """Пароль ящика: из окружения (если задано имя переменной) или из базы."""
    if account.secret_env:
        if not secret_env_allowed(account.secret_env):
            logger.warning("имя переменной с паролем не из почтового пространства имён")
            return decrypt(account.password_enc)
        env = os.environ.get(account.secret_env, "")
        if env:
            return env
    return decrypt(account.password_enc)
