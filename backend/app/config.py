import logging

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cl:clearledger@db:5432/clearledger"
    database_url_sync: str = "postgresql://cl:clearledger@db:5432/clearledger"
    storage_root: str = "/data/storage"
    secret_key: str = "dev-secret-change-in-production"
    cloud_api_url: str = ""
    cloud_api_key: str = ""
    instance_id: str = "dev-local"

    # CORS (через запятую: "http://localhost:3000,https://app.example.com")
    cors_origins: str = "http://localhost:3000,http://localhost:3010,http://localhost:8080"

    # JWT
    access_token_expire_minutes: int = 1440  # 24 часа
    algorithm: str = "HS256"

    # Rate limiting
    rate_limit: str = "60/minute"
    rate_limit_auth: str = "10/minute"

    model_config = {"env_file": ".env"}


settings = Settings()

# Предупреждение при дефолтном SECRET_KEY
if settings.secret_key == "dev-secret-change-in-production":
    logging.warning(
        "⚠️  SECRET_KEY не задан! Используется дефолтный ключ. "
        "В production задайте SECRET_KEY через переменную окружения."
    )
