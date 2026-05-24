"""
Подключение к PostgreSQL через asyncpg + SQLAlchemy 2.0 async.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


async def create_all() -> None:
    """Создаёт все таблицы (если не существуют) + инкрементальные миграции."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Инкрементальные миграции для существующих таблиц
    async with engine.begin() as conn:
        # v0.6: cloud_api_key для Companies (внешний доступ TSupport)
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE companies ADD COLUMN IF NOT EXISTS cloud_api_key VARCHAR(128) UNIQUE"
            )
        )
        # v0.7: mode для OneCConnection (odata | com) — поддержка стенда через COMConnector
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE onec_connections ADD COLUMN IF NOT EXISTS mode VARCHAR(10) NOT NULL DEFAULT 'odata'"
            )
        )
        # v0.8: реквизиты входящего документа (ТТН №+дата) и ВидОперации
        # для сверки ТТН-файл ↔ ПТУ и интерпретации проводок ОРП.
        # + period_status и discrepancy_* (см. docs/sverka-spec.md §7a):
        # обязательная отметка «закрытый период» и расхождений (включая копеечные).
        for stmt in (
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS external_number VARCHAR(200)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS external_date VARCHAR(20)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS operation_type VARCHAR(100)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS period_status VARCHAR(10) NOT NULL DEFAULT 'open'",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_summary VARCHAR(500)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_details JSONB",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_period_status ON accounting_docs(company_id, period_status)",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_discrepancy_status ON accounting_docs(company_id, discrepancy_status)",
            # v0.9: уникальные маппинги source_key → target_ref в рамках (company_id, kind)
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_reconcile_mappings ON reconcile_mappings(company_id, kind, source_key)",
            "CREATE INDEX IF NOT EXISTS idx_reconcile_mappings_target ON reconcile_mappings(company_id, kind, target_ref)",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency — асинхронная сессия БД."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
