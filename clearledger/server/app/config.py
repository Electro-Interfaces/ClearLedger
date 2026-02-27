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

    @property
    def cors_origin_list(self) -> list[str]:
        """Разбирает CORS_ORIGINS в список."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Кешированный экземпляр настроек."""
    return Settings()
