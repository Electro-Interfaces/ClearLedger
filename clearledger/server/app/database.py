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
            # v1.0: layer + derived_from_entry_id для DataEntry — 4-слойная архитектура §0.
            "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS layer VARCHAR(10) NOT NULL DEFAULT 'raw'",
            "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS derived_from_entry_id UUID REFERENCES data_entries(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS idx_data_entries_layer ON data_entries(company_id, layer)",
            "CREATE INDEX IF NOT EXISTS idx_data_entries_derived_from ON data_entries(derived_from_entry_id)",
            # Backfill: проставляем layer по существующему status — 'verified'/'transferred' → clean.
            "UPDATE data_entries SET layer = 'clean' WHERE layer = 'raw' AND status IN ('verified','transferred')",
            # v1.1: ExportPacket — L3 слой (что мы выгружаем в 1С).
            "CREATE INDEX IF NOT EXISTS idx_export_packets_status ON export_packets(company_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_export_packets_kind ON export_packets(company_id, kind)",
            # v1.2: OneCPolicy + PostingTemplate — учётная политика и схема проводок.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_onec_policies ON onec_policies(company_id, organization_external_ref, period)",
            "CREATE INDEX IF NOT EXISTS idx_posting_templates ON posting_templates(doc_type, operation_type)",
            # v1.3: NomenclaturePrice — срез РегС.ЦеныНоменклатуры.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_nomenclature_prices ON nomenclature_prices(company_id, nomenclature_ref, price_type_ref, period)",
            "CREATE INDEX IF NOT EXISTS idx_nomenclature_prices_lookup ON nomenclature_prices(company_id, nomenclature_ref, period DESC)",
            # v1.4: InventoryBatch — партии FIFO (РегистрНакопления.ПартииТоваровНаСкладах).
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_batches ON inventory_batches(company_id, batch_doc_ref, nomenclature_ref, warehouse_ref)",
            "CREATE INDEX IF NOT EXISTS idx_inventory_batches_nom ON inventory_batches(company_id, nomenclature_ref)",
            # v1.5: расширяем поля учётной политики (vat_rate может содержать "НДС 22% / Прибыль 25%")
            "ALTER TABLE onec_policies ALTER COLUMN vat_rate TYPE VARCHAR(100)",
            "ALTER TABLE onec_policies ALTER COLUMN mpz_method TYPE VARCHAR(100)",
            "ALTER TABLE onec_policies ALTER COLUMN tax_system TYPE VARCHAR(50)",
            # v1.6: source у InventoryBatch для меток "fallback:ТоварыНаСкладах"
            "ALTER TABLE inventory_batches ALTER COLUMN source TYPE VARCHAR(50)",
            # v1.7: price_type_ref с префиксом "catalog:" / "documents:" длиннее 36
            "ALTER TABLE nomenclature_prices ALTER COLUMN price_type_ref TYPE VARCHAR(64)",
            # v1.8 (блокер №1): натуральный ключ идемпотентности ExportPacket =
            # КлючЗагрузки нативного пути .cfe. Частичный UNIQUE среди НЕ-rejected
            # пакетов — DB-страховка от задвоения смены на живой бухгалтерии.
            "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS idem_key VARCHAR(120)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_packets_active_idem "
            "ON export_packets(company_id, idem_key) "
            "WHERE idem_key IS NOT NULL AND status <> 'rejected'",
            # Backfill idem_key из ранее записанного payload.marker (новые маркеры
            # уже = натуральному ключу; старые shift_orp:* останутся как есть).
            "UPDATE export_packets SET idem_key = payload->>'marker' "
            "WHERE idem_key IS NULL AND payload ? 'marker'",
            # v1.9: маппинг уровня КАНАЛА — channel_id (NULL=дефолт компании).
            # Значения топлива/оплат/станций различаются между системами →
            # настройка/оптимизация маппинга на уровне канала.
            "ALTER TABLE reconcile_mappings ADD COLUMN IF NOT EXISTS channel_id UUID "
            "REFERENCES channels(id) ON DELETE CASCADE",
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
