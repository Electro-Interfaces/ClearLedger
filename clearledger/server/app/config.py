"""
Конфигурация приложения.
Загружает переменные окружения из .env файла.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки ClearLedger Server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # База данных
    database_url: str = (
        "postgresql+asyncpg://clearledger:clearledger@localhost:5432/clearledger"
    )

    # Безопасность
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    access_token_expire_minutes: int = 1440  # 24 часа
    algorithm: str = "HS256"

    # CORS — список origin через запятую
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # OCR
    ocr_enabled: bool = True
    ocr_max_file_size: int = 10 * 1024 * 1024  # 10 МБ
    ocr_timeout: int = 30  # секунд

    # SMTP — отправка писем (приглашения сотрудников). Mailcow на services-01.
    # На проде SMTP_HOST=10.10.70.51 (внутренний IP хоста), 587 STARTTLS,
    # SMTP_SERVERNAME=mail.dataworker.ru для проверки TLS-сертификата.
    # Пусто → dev-режим: ссылка приглашения печатается в лог.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "TradeLedger <ledger@dataworker.ru>"
    smtp_servername: str = ""
    smtp_secure: bool = False  # True для 465 SMTPS; False для 587 STARTTLS

    # Публичный URL приложения для ссылок в письмах (с base-path).
    app_public_url: str = "https://ledger.dataworker.ru/ClearLedger"

    # Сверки — внешние API (прокси на стороне сервера, секреты не уходят на фронт)
    tradecorp_api_url: str = ""
    tradecorp_login: str = ""
    tradecorp_password: str = ""
    tradecorp_emitent_id: int = 15
    msto_api_url: str = ""
    msto_username: str = ""
    msto_password: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Разбирает CORS_ORIGINS в список."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Кешированный экземпляр настроек."""
    return Settings()
