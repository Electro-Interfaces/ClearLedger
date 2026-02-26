"""Конфигурация облачного AI-сервера."""

from pydantic_settings import BaseSettings


class CloudSettings(BaseSettings):
    api_keys: str = ""  # запятая-разделённые ключи клиентов
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"

    model_config = {"env_prefix": "CLOUD_", "env_file": ".env"}


settings = CloudSettings()


def verify_api_key(key: str) -> bool:
    """Проверка ключа клиента."""
    if not settings.api_keys:
        return True  # dev-режим без ключей
    allowed = [k.strip() for k in settings.api_keys.split(",")]
    return key in allowed
