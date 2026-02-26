from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cl:clearledger@db:5432/clearledger"
    database_url_sync: str = "postgresql://cl:clearledger@db:5432/clearledger"
    storage_root: str = "/data/storage"
    secret_key: str = "dev-secret-change-in-production"
    cloud_api_url: str = ""
    cloud_api_key: str = ""
    instance_id: str = "dev-local"

    # JWT
    access_token_expire_minutes: int = 1440  # 24 часа
    algorithm: str = "HS256"

    model_config = {"env_file": ".env"}


settings = Settings()
