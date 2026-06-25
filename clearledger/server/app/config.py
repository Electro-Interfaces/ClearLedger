"""
Конфигурация приложения.
Загружает переменные окружения из .env файла.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значение секрета по умолчанию — заведомо небезопасное. Если оно доедет до
# прода, JWT можно подделать публично известным ключом. main.lifespan проверяет
# и кричит в лог; деплой обязан задать SECRET_KEY (или JWT_SECRET).
DEFAULT_INSECURE_SECRET = "change-me-in-production-use-openssl-rand-hex-32"


class Settings(BaseSettings):
    """Настройки TradeLedger Server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # База данных
    database_url: str = (
        "postgresql+asyncpg://clearledger:clearledger@localhost:5432/clearledger"
    )

    # Безопасность. Секрет читается из SECRET_KEY ИЛИ JWT_SECRET — историческое
    # расхождение имён (прод-compose отдавал JWT_SECRET, а приложение ждало
    # SECRET_KEY → втихую брался дефолт). AliasChoices принимает оба.
    secret_key: str = Field(
        default=DEFAULT_INSECURE_SECRET,
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET"),
    )
    access_token_expire_minutes: int = 1440  # 24 часа
    algorithm: str = "HS256"

    # Сид суперадмина. Создаётся при старте ТОЛЬКО если заданы обе переменные
    # (SEED_SUPERADMIN_EMAIL + SEED_SUPERADMIN_PASSWORD). Пусто → суперадмин на
    # старте НЕ создаётся (нет дефолтного бэкдора admin@clearledger.ru/admin123).
    seed_superadmin_email: str = ""
    seed_superadmin_password: str = ""

    @property
    def secret_is_insecure(self) -> bool:
        """Секрет не задан в окружении (используется небезопасный дефолт)?"""
        return self.secret_key == DEFAULT_INSECURE_SECRET

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
    # ⚠ Путь = /ClearLedger (vite base + nginx), хотя имя продукта TradeLedger.
    # Переименование пути /ClearLedger→/TradeLedger — отдельная риск-миграция.
    app_public_url: str = "https://ledger.dataworker.ru/ClearLedger"

    # Сверки — внешние API (прокси на стороне сервера, секреты не уходят на фронт)
    tradecorp_api_url: str = ""
    tradecorp_login: str = ""
    tradecorp_password: str = ""
    tradecorp_emitent_id: int = 15
    msto_api_url: str = ""
    msto_username: str = ""
    msto_password: str = ""

    # HubEx FSM — сервисные заявки/ремонты ЭЗС РусГидро (прокси на сервере,
    # сервисный токен НЕ уходит на фронт). Пусто → вкладка «Сервис» без заявок.
    hubex_service_token: str = ""
    hubex_base_url: str = "https://api.hubex.ru/fsm"
    hubex_app_id: str = "5"
    hubex_tasks_limit: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        """Разбирает CORS_ORIGINS в список."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Кешированный экземпляр настроек."""
    return Settings()
