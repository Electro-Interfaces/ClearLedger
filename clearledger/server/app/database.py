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
            # v0.9: индекс по target (обратный поиск). Уникальность маппингов —
            # частичные индексы в v1.9 (с учётом channel_id).
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
            # v2.5: уникальность смены STS (станция + номер) — защита от дублей при
            # параллельных прогонах канала fuel_shift с поэтапным commit.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_fuel_shifts_station_number "
            "ON fuel_shifts(station_id, shift_number)",
            # v2.6: детали смены как в TradeFrame — счётчики ТРК, параметры
            # резервуаров, движение наличных (fuel_cash_movements создаётся create_all).
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS fuel_code INTEGER",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS volume_received NUMERIC(12,2) NOT NULL DEFAULT 0",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS density_beg NUMERIC(6,4)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS temp_end NUMERIC(6,2)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS level_end NUMERIC(10,2)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS water_level NUMERIC(10,2)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS water_volume NUMERIC(12,2)",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS fuel_code INTEGER",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS tank_number INTEGER",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS psm_beg NUMERIC(14,2)",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS psm_end NUMERIC(14,2)",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS price NUMERIC(8,2)",
            "ALTER TABLE fuel_pumps ADD COLUMN IF NOT EXISTS density NUMERIC(6,4)",
            # v2.9: сырой сменный отчёт STS на смене — вход эталонного просмотрщика
            # TradeFrame (форма «Детали смены» строится адаптером из этого JSON).
            "ALTER TABLE fuel_shifts ADD COLUMN IF NOT EXISTS raw_report JSONB",
            # v4.0: гео-паспорт АЗС (координаты/адрес из STS /v1/points) — для Карты АЗС.
            "ALTER TABLE fuel_stations ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
            "ALTER TABLE fuel_stations ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
            "ALTER TABLE fuel_stations ADD COLUMN IF NOT EXISTS address VARCHAR(300)",
            # v3.1: период прогона в логе — для ленты прогонов кокпита канала
            # (строка прогона показывает, за какой период он грузил).
            "ALTER TABLE channel_sync_logs ADD COLUMN IF NOT EXISTS date_from VARCHAR(10)",
            "ALTER TABLE channel_sync_logs ADD COLUMN IF NOT EXISTS date_to VARCHAR(10)",
            # v3.2: онлайн-заказы MSTO — натуральный ключ идемпотентности ingest
            # (повторный прогон периода не плодит дубли заказов).
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_online_orders_ext "
            "ON online_orders(company_id, external_id)",
            # v3.3: канон топлива (резолв имени MSTO → эталон компании).
            "ALTER TABLE online_orders ADD COLUMN IF NOT EXISTS fuel_code INTEGER",
            # v3.4: роль разреза учёта на потоке канала (anchor/control/reference);
            # бэкафилл из шаблонов — в seed (_backfill_channel_cuts).
            "ALTER TABLE channel_streams ADD COLUMN IF NOT EXISTS role VARCHAR(20) "
            "NOT NULL DEFAULT 'control'",
            # v3.5: разрез может быть предустановлен без подключённого источника.
            "ALTER TABLE channel_streams ALTER COLUMN source_id DROP NOT NULL",
            # v3.6: зарядные сессии ЭЗС — привязка к каналу-обработчику (цепочка).
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS channel_id UUID "
            "REFERENCES channels(id) ON DELETE SET NULL",
            # v3.7: обогащение сессий — наименование корпоративного клиента (ЮЛ),
            # проставляется джойном справочника «Организации» по телефону (user_id).
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS client_name VARCHAR(300)",
            "CREATE INDEX IF NOT EXISTS ix_charge_sessions_user_id ON charge_sessions (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_charge_sessions_client_name ON charge_sessions (client_name)",
            # v3.8: договорной тариф корп-клиента + вычисленная корп-выручка.
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS client_tariff NUMERIC(10,2)",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS client_amount NUMERIC(14,2)",
            # v3.0: натуральный ключ ТТН — дедуп существующих дублей + уникальный
            # индекс (DB-страховка от задвоения; как уже дедуплицирует delivery-ветка
            # по (company, station, ttn, code)). COALESCE(fuel_code,-1) — чтобы NULL
            # не плодил дубли; частичный WHERE ttn<>'' — пустые ТТН не индексируем.
            "DELETE FROM fuel_receipts a USING fuel_receipts b "
            "WHERE a.id > b.id AND a.company_id = b.company_id "
            "AND a.station_id = b.station_id AND a.ttn = b.ttn "
            "AND a.fuel_code IS NOT DISTINCT FROM b.fuel_code AND a.ttn <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_fuel_receipts_natural "
            "ON fuel_receipts (company_id, station_id, ttn, COALESCE(fuel_code, -1)) "
            "WHERE ttn <> ''",
            # v3.1: реквизиты журнала/деталей поступления (как TradePoint).
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS shift_number INTEGER",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS tank INTEGER",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS doc_temp NUMERIC(6,2)",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS fact_temp NUMERIC(6,2)",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS fact_density NUMERIC(6,4)",
            # v3.2: единый справочник видов топлива — привязка номенклатуры 1С
            # по GUID (т/л). fuel_mappings = единый источник правды; reconcile-fuel
            # выводится из него. Backfill GUID/имени литров из существующего
            # reconcile-маппинга 'fuel' (там уже выбрана номенклатура 1С).
            "ALTER TABLE fuel_mappings ADD COLUMN IF NOT EXISTS nomenclature_t_ref VARCHAR(36)",
            "ALTER TABLE fuel_mappings ADD COLUMN IF NOT EXISTS nomenclature_l_ref VARCHAR(36)",
            "UPDATE fuel_mappings fm "
            "SET nomenclature_l_ref = rm.target_ref, "
            "    nomenclature_liters = COALESCE(NULLIF(rm.target_name,''), fm.nomenclature_liters) "
            "FROM reconcile_mappings rm "
            "WHERE rm.company_id = fm.company_id AND rm.kind = 'fuel' AND rm.channel_id IS NULL "
            "  AND rm.source_key = fm.service_code::text AND fm.nomenclature_l_ref IS NULL",
            # v1.9: маппинг уровня КАНАЛА — channel_id (NULL=дефолт компании).
            # Значения топлива/оплат/станций различаются между системами →
            # настройка/оптимизация маппинга на уровне канала.
            "ALTER TABLE reconcile_mappings ADD COLUMN IF NOT EXISTS channel_id UUID "
            "REFERENCES channels(id) ON DELETE CASCADE",
            # Уникальность с учётом channel_id: один дефолт компании (channel_id IS NULL)
            # на ключ + один override на канал. Прежний индекс без channel_id запрещал
            # override (конфликт с дефолтом) → заменяем на два частичных индекса.
            "DROP INDEX IF EXISTS uq_reconcile_mappings",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_reconcile_mappings_company "
            "ON reconcile_mappings(company_id, kind, source_key) WHERE channel_id IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_reconcile_mappings_channel "
            "ON reconcile_mappings(company_id, kind, source_key, channel_id) WHERE channel_id IS NOT NULL",
            # v2.3: расширенные реквизиты организации (полное наим., ОКПО, адреса,
            # контакты, ответственные лица) — карточка «Организация» в разделе Загрузка.
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS full_name VARCHAR(500)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS okpo VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS legal_address TEXT",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS actual_address TEXT",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS phone VARCHAR(100)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS director_name VARCHAR(255)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS director_position VARCHAR(150)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS accountant_name VARCHAR(255)",
            # v2.4: полная карточка организации БП 3.0 — вид, гос.регистрация,
            # налоговая/фонды, почт.адрес, факс, кассир.
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS vid VARCHAR(40)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS prefix VARCHAR(10)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS reg_date VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS okved VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS oktmo VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS okato VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS okopf VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS okfs VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS registration_cert VARCHAR(300)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ifns_code VARCHAR(10)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ifns_name VARCHAR(300)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS pfr_reg_number VARCHAR(30)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS fss_reg_number VARCHAR(30)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS fss_subordination VARCHAR(10)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS postal_address TEXT",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS fax VARCHAR(100)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cashier_name VARCHAR(255)",
            # v2.5: полная карточка контрагента (ОГРН/ОКВЭД/адреса/контакты/руководитель/банк).
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS ogrn VARCHAR(20)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS okved VARCHAR(20)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS legal_address TEXT",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS actual_address TEXT",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS phone VARCHAR(100)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS director_name VARCHAR(255)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS director_position VARCHAR(150)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS bank_account VARCHAR(30)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS bank_bik VARCHAR(12)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS bank_name VARCHAR(255)",
            # v2.6: полная карточка договора (НДС, вид взаиморасчётов, комментарий).
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS vat_rate VARCHAR(20)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS amount_incl_vat BOOLEAN",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS settlement_kind VARCHAR(150)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS comment TEXT",
            # v2.0: мультитенантность — членство user↔company (M2M) + суперадмин.
            # Порядок важен: сначала колонка, потом снять NOT NULL с company_id,
            # затем таблица членства, затем backfill из текущей company_id, затем
            # демо-админ → суперадмин (иначе он привязан только к npk и теряет
            # доступ к остальным компаниям).
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN NOT NULL DEFAULT FALSE",
            # Восстановление пароля по email (одноразовый токен + срок).
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(64)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMPTZ",
            "ALTER TABLE users ALTER COLUMN company_id DROP NOT NULL",
            "CREATE TABLE IF NOT EXISTS user_companies ("
            "  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,"
            "  role VARCHAR(20) NOT NULL DEFAULT 'user',"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (user_id, company_id))",
            # Гарантируем дефолт role ДО backfill-INSERT (на случай, если таблицу
            # создал ORM create_all без server_default — тогда INSERT без role упал бы).
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS role VARCHAR(20)",
            "ALTER TABLE user_companies ALTER COLUMN role SET DEFAULT 'user'",
            "UPDATE user_companies SET role = 'user' WHERE role IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_user_companies_company ON user_companies(company_id)",
            "INSERT INTO user_companies (user_id, company_id) "
            "SELECT id, company_id FROM users WHERE company_id IS NOT NULL "
            "ON CONFLICT DO NOTHING",
            "UPDATE users SET is_superadmin = TRUE WHERE email = 'admin@clearledger.ru'",
            # v2.1: роль-на-компанию — роль пользователя в КОНКРЕТНОЙ компании.
            # Backfill: текущие глобальные админы становятся админами своих компаний.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'",
            "UPDATE user_companies uc SET role = 'admin' "
            "FROM users u WHERE uc.user_id = u.id AND u.role = 'admin'",
            # v2.3: RBAC — модули доступа члена компании. NULL = полный доступ.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS modules JSONB",
            # v2.4: hybrid RBAC — назначенная именованная роль (company_roles).
            # Таблицу company_roles создаёт create_all; здесь только колонка role_id.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS role_id UUID",
            # v2.2: приглашения сотрудников по email.
            "CREATE TABLE IF NOT EXISTS invitations ("
            "  id UUID PRIMARY KEY,"
            "  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,"
            "  email VARCHAR(255) NOT NULL,"
            "  role VARCHAR(20) NOT NULL DEFAULT 'user',"
            "  token_hash VARCHAR(64) NOT NULL UNIQUE,"
            "  status VARCHAR(20) NOT NULL DEFAULT 'pending',"
            "  invited_by UUID REFERENCES users(id) ON DELETE SET NULL,"
            "  expires_at TIMESTAMPTZ NOT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  accepted_at TIMESTAMPTZ)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_company ON invitations(company_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token_hash)",
            # v2.3: должность сотрудника (per-company) + в приглашении.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS position VARCHAR(150)",
            "ALTER TABLE invitations ADD COLUMN IF NOT EXISTS position VARCHAR(150)",
            # v2.5: универсальные справочники — raw-снимок всех реквизитов 1С + промо.
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS raw JSONB",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS full_name VARCHAR(1000)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS okpo VARCHAR(20)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS head_ref VARCHAR(36)",
            "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'external'",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS raw JSONB",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS kind VARCHAR(40)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS currency VARCHAR(10)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS valid_until VARCHAR(20)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS is_closed BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20) NOT NULL DEFAULT 'unassigned'",
            # v2.6: паспорт ЭЗС-станции в service_locations (нормализованный L2 из справочника станций)
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS serial_number VARCHAR(120)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS station_number VARCHAR(60)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS city VARCHAR(120)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS street VARCHAR(200)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS house VARCHAR(40)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS power_kwt DOUBLE PRECISION",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS connectors_count INTEGER",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS connector_types VARCHAR(200)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS owner VARCHAR(200)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS owner_id INTEGER",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS brand VARCHAR(120)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS model VARCHAR(120)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS ocpp_protocol VARCHAR(40)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS firmware VARCHAR(80)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS stage VARCHAR(40)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS access_type VARCHAR(60)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS is_published BOOLEAN",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS hubex_asset_id VARCHAR(80)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS hubex_link_status VARCHAR(40)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS rating DOUBLE PRECISION",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS success_pct DOUBLE PRECISION",
            "CREATE INDEX IF NOT EXISTS idx_service_locations_type ON service_locations(company_id, type)",
            # v2.7: материализованная связь сессии → объект-станция (конформная размерность)
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS location_id VARCHAR(40) REFERENCES service_locations(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS idx_charge_sessions_location ON charge_sessions(location_id)",
            # v2.8: скидка корп-клиента к рознице (каршеринг = 25%; применяется к матрице)
            "ALTER TABLE corporate_clients ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0",
            # v3.9: составные индексы под шаблон WHERE аналитики «Продаж». Одиночный
            # company_id неселективен (≈одна компания на всю таблицу) — диапазонные
            # сканы опирались на голый ix_started_at. Составные ускоряют overview/
            # retail/corporate (диапазон по started_at + сегмент).
            "CREATE INDEX IF NOT EXISTS idx_cs_company_started "
            "ON charge_sessions (company_id, started_at)",
            # розница ФЛ: user_id NOT NULL AND client_name IS NULL (retail_service._accounts)
            "CREATE INDEX IF NOT EXISTS idx_cs_retail_started "
            "ON charge_sessions (company_id, started_at, user_id) "
            "WHERE client_name IS NULL AND user_id IS NOT NULL",
            # корпоратив ЮЛ: client_name NOT NULL (corporate_service/billing)
            "CREATE INDEX IF NOT EXISTS idx_cs_corp_started "
            "ON charge_sessions (company_id, client_name, started_at) "
            "WHERE client_name IS NOT NULL",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.4: встроенный каталог типов точек. Таблица location_types создаётся
        # через metadata.create_all; здесь — идемпотентный сид системных типов
        # (company_id=NULL, is_builtin=true). ON CONFLICT DO NOTHING ловит
        # частичный uq-индекс по коду встроенных типов.
        import json as _json
        import uuid as _uuid
        from app.location_type_defaults import BUILTIN_LOCATION_TYPES
        # UPSERT: код-канонические встроенные типы обновляются из кода
        # (новые поля/лейблы доезжают на старте). Кастомные типы компаний не
        # затрагиваются (частичный uq-индекс по company_id IS NULL).
        _ins_lt = __import__("sqlalchemy").text(
            "INSERT INTO location_types "
            "(id, company_id, code, name, icon, unit, nomenclature_kind, fields, "
            " is_builtin, sort_order, status) "
            "VALUES (CAST(:id AS UUID), NULL, :code, :name, :icon, :unit, :kind, "
            " CAST(:fields AS JSONB), true, :sort, 'active') "
            "ON CONFLICT (code) WHERE company_id IS NULL DO UPDATE SET "
            " name = EXCLUDED.name, icon = EXCLUDED.icon, unit = EXCLUDED.unit, "
            " nomenclature_kind = EXCLUDED.nomenclature_kind, "
            " fields = EXCLUDED.fields, sort_order = EXCLUDED.sort_order"
        )
        for _t in BUILTIN_LOCATION_TYPES:
            await conn.execute(_ins_lt, {
                "id": str(_uuid.uuid4()),
                "code": _t["code"], "name": _t["name"], "icon": _t["icon"],
                "unit": _t["unit"], "kind": _t["nomenclature_kind"],
                "fields": _json.dumps(_t["fields"], ensure_ascii=False),
                "sort": _t["sort_order"],
            })

        # v2.5: операционный статус точки (работает/ремонт/...) — отдельно от
        # жизненного цикла status; история смен — в audit_events.
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS "
            "operational_status VARCHAR(20) NOT NULL DEFAULT 'unknown'"
        ))

        # v2.7: Сервисный центр (netservice). Таблицы regions/hubex_tasks/
        # hubex_assets/hubex_refs/support_sync_cursors создаются через
        # metadata.create_all (индексы — из __table_args__ моделей). Здесь —
        # колонка region_id у существующей service_locations + идемпотентный
        # бэкфилл регионов из extra_metadata.federalSubject (сырьё остаётся в
        # metadata; region_id — производный быстрый разрез для аналитики).
        for stmt in (
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS region_id UUID "
            "REFERENCES regions(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS idx_service_locations_region "
            "ON service_locations(company_id, region_id)",
            # Уникальные federalSubject → regions
            "INSERT INTO regions (id, company_id, name, federal_subject) "
            "SELECT gen_random_uuid(), company_id, extra_metadata->>'federalSubject', "
            "       extra_metadata->>'federalSubject' "
            "FROM service_locations "
            "WHERE extra_metadata->>'federalSubject' IS NOT NULL "
            "  AND extra_metadata->>'federalSubject' <> '' "
            "GROUP BY company_id, extra_metadata->>'federalSubject' "
            "ON CONFLICT (company_id, name) DO NOTHING",
            # Проставить region_id точкам по совпадению названия региона
            "UPDATE service_locations sl SET region_id = r.id "
            "FROM regions r "
            "WHERE sl.region_id IS NULL AND r.company_id = sl.company_id "
            "  AND r.name = sl.extra_metadata->>'federalSubject'",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.8: платёжная дисциплина по станциям (реестр «Договоры и оплаты ЭЗС»,
        # energy/РусГидро). Таблица station_contract_settlements создаётся через
        # metadata.create_all (индексы — из __table_args__). Здесь — колонка basis
        # у contracts (основание обязательства: договор|разрешение|постановление|…).
        # См. SOURCE_CONTRACTS_PAYMENTS_RUSHYDRO.md.
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS basis VARCHAR(100)"
        ))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency — асинхронная сессия БД."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
