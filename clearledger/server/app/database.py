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
            # v4.1: удельная себестоимость остатка (ПартииТоваровНаСкладах Стоимость/Количество)
            "ALTER TABLE stock_on_hand ADD COLUMN IF NOT EXISTS cost_unit NUMERIC(16,4)",
            # v4.3: единица измерения номенклатуры (карточка товароведа)
            "ALTER TABLE cb_nomenclature ADD COLUMN IF NOT EXISTS unit VARCHAR(30)",
            # v4.4: полное наименование + основной поставщик (карточка товароведа)
            "ALTER TABLE cb_nomenclature ADD COLUMN IF NOT EXISTS full_name VARCHAR(700)",
            "ALTER TABLE cb_nomenclature ADD COLUMN IF NOT EXISTS main_supplier VARCHAR(300)",
            # v4.5: НСИ-реквизиты для эмиттера пакета БП (КодЦБ + orgs/warehouses)
            "ALTER TABLE cb_nomenclature ADD COLUMN IF NOT EXISTS code VARCHAR(40)",
            "ALTER TABLE cb_ref ADD COLUMN IF NOT EXISTS extra JSONB",
            # v4.2: индексы под аналитику магазина (К-27)
            "CREATE INDEX IF NOT EXISTS ix_data_entries_store ON data_entries (company_id, layer, doc_type_id)",
            "CREATE INDEX IF NOT EXISTS ix_stock_on_hand_wh ON stock_on_hand (company_id, warehouse_code)",
            # v3.1: период прогона в логе — для ленты прогонов кокпита канала
            # (строка прогона показывает, за какой период он грузил).
            "ALTER TABLE channel_sync_logs ADD COLUMN IF NOT EXISTS date_from VARCHAR(10)",
            "ALTER TABLE channel_sync_logs ADD COLUMN IF NOT EXISTS date_to VARCHAR(10)",
            # v3.2: онлайн-заказы MSTO — натуральный ключ идемпотентности ingest
            # (повторный прогон периода не плодит дубли заказов).
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_online_orders_ext "
            "ON online_orders(company_id, external_id)",
            "CREATE INDEX IF NOT EXISTS idx_online_orders_company_date "
            "ON online_orders(company_id, order_date)",
            "CREATE INDEX IF NOT EXISTS idx_online_orders_station_date "
            "ON online_orders(company_id, station_id, order_date)",
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
            # Принадлежность участника пространства: свой сотрудник или внешний
            # (подрядчик/поставщик/представитель заказчика). Права — отдельно, в role;
            # это про «кто с кем разговаривает» в чатах, заявках и справочнике людей.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS party_type VARCHAR(20) "
            "NOT NULL DEFAULT 'internal'",
            # Какую организацию представляет внешний участник (карточка юрлица пространства).
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS organization_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
            # Скоуп данных: объекты, которые видит участник (NULL = вся сеть компании).
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS object_scope JSONB",
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
            # Принадлежность задаётся в приглашении: человек входит сразу своим
            # сотрудником или представителем компании-партнёра (с её карточкой юрлица).
            "ALTER TABLE invitations ADD COLUMN IF NOT EXISTS party_type VARCHAR(20) "
            "NOT NULL DEFAULT 'internal'",
            "ALTER TABLE invitations ADD COLUMN IF NOT EXISTS organization_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
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
            # v4.0: ВИЗИТ — склейка смежных попыток одного клиента на одной станции.
            # CPO отдаёт каждую попытку подключения отдельной строкой: клиент тыкает
            # разъём 3-4 раза, первые попытки падают, последняя заряжает. Сырой
            # «успех сессий» = 69% описывает не сеть, а поведение разъёма; успех
            # ВИЗИТА (зарядился ли человек) = 88,9%. Поля считает charge_visits.py.
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS visit_key VARCHAR(80)",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS visit_seq INTEGER",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS visit_size INTEGER",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS visit_charged BOOLEAN",
            "CREATE INDEX IF NOT EXISTS idx_cs_visit "
            "ON charge_sessions (company_id, visit_key)",
            # v4.6: пробел в продажах смены. STS не отдаёт детализацию (psm/sales)
            # по сменам АЗС 205/207/208/209/210/9008 до их подключения к контуру
            # (янв–фев 2026) — при живой кассе и ТТН. 721 такая смена лежала с
            # выручкой 0 и занижала средние. Это не ноль, а отсутствие данных.
            "ALTER TABLE fuel_shifts ADD COLUMN IF NOT EXISTS sales_missing "
            "BOOLEAN NOT NULL DEFAULT false",
            # Бэкфилл: отчёт снят, но продаж в нём нет вовсе (ни psm.total, ни sales).
            # Смена с непустым psm и нулевым объёмом — честный ноль, её не метим.
            "UPDATE fuel_shifts SET sales_missing = true "
            "WHERE total_amount = 0 AND raw_report IS NOT NULL "
            "AND jsonb_array_length(coalesce(raw_report->'psm'->'total','[]'::jsonb)) = 0 "
            "AND jsonb_array_length(coalesce(raw_report->'sales','[]'::jsonb)) = 0 "
            "AND sales_missing = false",
            # v4.7: факт замера и масса по резервуарам. STS отдавал их всегда
            # (секции `rest` и `amount` в release[]), но приём брал только книжные
            # литры — сравнить книгу с фактом было физически не с чем.
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS fact_volume NUMERIC(12,2)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS fact_mass NUMERIC(14,3)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS mass_start NUMERIC(14,3)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS mass_end NUMERIC(14,3)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS mass_sales NUMERIC(14,3)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS mass_received NUMERIC(14,3)",
            "ALTER TABLE fuel_tanks ADD COLUMN IF NOT EXISTS temp_beg NUMERIC(6,2)",
            # Бэкфилл из уже сохранённых сырых отчётов — перекачивать STS не нужно,
            # цифры лежат в fuel_shifts.raw_report с первого дня приёма.
            """
            UPDATE fuel_tanks t SET
                fact_volume   = nullif(r.rec->'rest'->>'volume','')::numeric,
                fact_mass     = nullif(r.rec->'rest'->>'amount','')::numeric,
                mass_start    = nullif(r.rec->'doc_beg'->>'amount','')::numeric,
                mass_end      = nullif(r.rec->'doc_end'->>'amount','')::numeric,
                mass_sales    = nullif(r.rec->'release'->>'amount','')::numeric,
                mass_received = nullif(r.rec->'receipt'->>'amount','')::numeric,
                temp_beg      = nullif(r.rec->>'temp_beg','')::numeric
            FROM (
                SELECT s.id AS shift_id, (e.rec->>'tank')::int AS tank_number, e.rec
                FROM fuel_shifts s,
                     LATERAL jsonb_array_elements(s.raw_report->'release') AS e(rec)
                WHERE s.raw_report ? 'release'
                  AND jsonb_typeof(s.raw_report->'release') = 'array'
                  AND (e.rec->>'tank') ~ '^[0-9]+$'
            ) r
            WHERE t.shift_id = r.shift_id AND t.tank_number = r.tank_number
              AND t.fact_volume IS NULL
            """,
            # v4.8: «замера не было» — это NULL, а не 0. Приём пишет
            # `_f(rest.volume) or None` (ноль → NULL), а бэкфилл v4.7 брал
            # nullif(...,'') — он снимает пустую строку, но "0.00" сохранял как 0.
            # Из-за асимметрии 554 записи ГИГ читались как «в резервуаре пусто»:
            # книга − факт = весь книжный остаток (мнимая недостача 611 тыс. л),
            # а ведомость инвентаризации списала бы резервуар целиком.
            "UPDATE fuel_tanks SET fact_volume = NULL WHERE fact_volume = 0",
            "UPDATE fuel_tanks SET fact_mass = NULL WHERE fact_mass = 0",
            # v4.9: накладные приёма — восстановление связи со сменой.
            # ТТН лежит прямо в сменном отчёте (секция `receipt` верхнего уровня:
            # ttn, shift, tank, dt, base, doc/fact по объёму и массе). Но приём
            # шёл двумя путями: через смену (shift_id проставлялся) и каналом
            # fuel_delivery (shift_id=None — «приём не кассовое событие»), а дедуп
            # по (company, station, ttn, code) оставлял ту запись, что пришла первой.
            # На ГИГ первым отработал канал → у всех 1163 записей связи не было,
            # и сверить «слил по накладной ↔ принял резервуар в смене» было нечем.
            # Связь берём из источника (точная), а не подбором по объёму.
            # Заодно чиним `tank`: в таблице он сбит (в одной ТТН все виды топлива
            # оказывались на резервуаре 1), а в отчёте у каждой строки свой.
            """
            WITH rep AS (
                SELECT s.company_id, s.station_id, s.id AS shift_id, s.shift_number,
                       trim(e.rec->>'ttn')                              AS ttn,
                       nullif(e.rec->'service'->>'service_code','')::int AS fuel_code,
                       nullif(e.rec->>'tank','')::int                    AS tank,
                       row_number() OVER (
                           PARTITION BY s.company_id, s.station_id, trim(e.rec->>'ttn'),
                                        nullif(e.rec->'service'->>'service_code','')::int
                           ORDER BY s.opened_at) AS rn
                  FROM fuel_shifts s,
                       LATERAL jsonb_array_elements(s.raw_report->'receipt') AS e(rec)
                 WHERE s.raw_report ? 'receipt'
                   AND jsonb_typeof(s.raw_report->'receipt') = 'array'
                   AND coalesce(trim(e.rec->>'ttn'), '') <> ''
            )
            UPDATE fuel_receipts r
               SET shift_id     = rep.shift_id,
                   shift_number = coalesce(rep.shift_number, r.shift_number),
                   tank         = coalesce(rep.tank, r.tank)
              FROM rep
             WHERE rep.rn = 1
               AND r.shift_id IS NULL
               AND r.company_id = rep.company_id
               AND r.station_id = rep.station_id
               AND trim(r.ttn)  = rep.ttn
               AND r.fuel_code IS NOT DISTINCT FROM rep.fuel_code
            """,
            # v4.9 (2): добор накладных, которые есть в сменных отчётах, но в
            # таблицу приёма не попали (на ГИГ ~83 ТТН из 720). Из-за этого приход
            # в резервуары не сходился с ТТН на 30-40%, и расхождение списывали на
            # перекачки. Плотность STS отдаёт в кг/м³ (≈700-900) — колонка
            # Numeric(6,4), поэтому делим на 1000, как это делает _density().
            """
            INSERT INTO fuel_receipts (
                id, company_id, station_id, shift_id, shift_number, tank, ttn,
                fuel_name, fuel_code, supplier,
                doc_volume_liters, doc_mass_kg, doc_cost,
                fact_volume_liters, fact_mass_kg, fact_cost,
                density, fact_density, doc_temp, fact_temp,
                diff_volume, diff_mass, received_at, status, is_locked, source_uuid)
            SELECT gen_random_uuid(), m.company_id, m.station_id, m.shift_id,
                   m.shift_number, m.tank, m.ttn,
                   coalesce(m.fuel_name, ''), m.fuel_code, m.supplier,
                   m.doc_v, m.doc_m, 0, m.fact_v, m.fact_m, 0,
                   m.doc_d, m.fact_d, m.doc_t, m.fact_t,
                   round(m.fact_v - m.doc_v, 2), round(m.fact_m - m.doc_m, 2),
                   m.dt, 'new', false, gen_random_uuid()
              FROM (
                SELECT DISTINCT ON (s.company_id, s.station_id, trim(e.rec->>'ttn'),
                                    nullif(e.rec->'service'->>'service_code','')::int)
                       s.company_id, s.station_id, s.id AS shift_id, s.shift_number,
                       trim(e.rec->>'ttn')                               AS ttn,
                       nullif(e.rec->>'tank','')::int                    AS tank,
                       e.rec->'service'->>'service_name'                 AS fuel_name,
                       nullif(e.rec->'service'->>'service_code','')::int AS fuel_code,
                       e.rec->'base'->>'name'                            AS supplier,
                       coalesce(nullif(e.rec->'doc'->>'volume','')::numeric, 0)  AS doc_v,
                       coalesce(nullif(e.rec->'doc'->>'amount','')::numeric, 0)  AS doc_m,
                       coalesce(nullif(e.rec->'fact'->>'volume','')::numeric, 0) AS fact_v,
                       coalesce(nullif(e.rec->'fact'->>'amount','')::numeric, 0) AS fact_m,
                       round(nullif(e.rec->'doc'->>'density','')::numeric  / 1000, 4) AS doc_d,
                       round(nullif(e.rec->'fact'->>'density','')::numeric / 1000, 4) AS fact_d,
                       nullif(e.rec->'doc'->>'temp','')::numeric          AS doc_t,
                       nullif(e.rec->'fact'->>'temp','')::numeric         AS fact_t,
                       coalesce(nullif(e.rec->>'dt','')::timestamptz, s.opened_at) AS dt
                  FROM fuel_shifts s,
                       LATERAL jsonb_array_elements(s.raw_report->'receipt') AS e(rec)
                 WHERE s.raw_report ? 'receipt'
                   AND jsonb_typeof(s.raw_report->'receipt') = 'array'
                   AND coalesce(trim(e.rec->>'ttn'), '') <> ''
                 ORDER BY s.company_id, s.station_id, trim(e.rec->>'ttn'),
                          nullif(e.rec->'service'->>'service_code','')::int, s.opened_at
              ) m
             WHERE NOT EXISTS (
                SELECT 1 FROM fuel_receipts x
                 WHERE x.company_id = m.company_id
                   AND x.station_id = m.station_id
                   AND trim(x.ttn)  = m.ttn
                   AND x.fuel_code IS NOT DISTINCT FROM m.fuel_code)
            """,
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

        # v2.9: bp-export — Проведен/ПометкаУдаления документов ЦБ (аудит 13.07):
        # инвентаризации полными строками (+ДатаЗаполнения), списания со ссылкой
        # на инвентаризацию-основание. Данные наполняет пул с боевой ЦБ (dev→prod).
        for stmt in (
            "ALTER TABLE cb_inventory_doc ADD COLUMN IF NOT EXISTS posted BOOLEAN NOT NULL DEFAULT true",
            "ALTER TABLE cb_inventory_doc ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE cb_inventory_doc ADD COLUMN IF NOT EXISTS fill_date VARCHAR(30)",
            "ALTER TABLE cb_movement_doc ADD COLUMN IF NOT EXISTS posted BOOLEAN NOT NULL DEFAULT true",
            "ALTER TABLE cb_movement_doc ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE cb_movement_doc ADD COLUMN IF NOT EXISTS inventory_ref VARCHAR(36)",
            # v3.0: аудит L2 (13.07) — индексы под частые паттерны (роллап смен по
            # дню закрытия, журнал поступлений по дате приёмки).
            "CREATE INDEX IF NOT EXISTS idx_fuel_shifts_company_closed ON fuel_shifts(company_id, closed_at)",
            "CREATE INDEX IF NOT EXISTS idx_fuel_receipts_company_received ON fuel_receipts(company_id, received_at)",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.10: реестры РусГидро (новый входной поток «Сводная»/«Договоры_Аренда»/
        # «Тарифы Электроэнергия_Входящие») — суммы и сроки на платёжной дисциплине;
        # station_energy_periods создаётся через metadata.create_all.
        for stmt in (
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS amount_gross DOUBLE PRECISION",
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS amount_net DOUBLE PRECISION",
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS vat_pct DOUBLE PRECISION",
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS contract_start VARCHAR(20)",
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS contract_end VARCHAR(20)",
            "ALTER TABLE station_contract_settlements ADD COLUMN IF NOT EXISTS extra JSONB",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.11: чистка «пустых дат 1С» в договорах (OData отдаёт 0001/0100-01-01,
        # старый синк сохранял их как есть → в UI мусор «0100-01-01»). Синк теперь
        # отбрасывает такие даты на входе; здесь — чистка уже сохранённых строк.
        for stmt in (
            "UPDATE contracts SET valid_until = NULL WHERE valid_until < '1900-01-01'",
            "UPDATE contracts SET date = '' WHERE date <> '' AND date < '1900-01-01'",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.12: аналитика продаж ГИГ по наливам (раздел «Продажи» → Аналитика/
        # Коммерция). Индекс под когорты «новые карты» (MIN(dt) GROUP BY card по
        # всей истории) и реестр карт. Досев паттернов маппинга оплат: на
        # ТРАНЗАКЦИОННОМ грейне STS имена видов оплаты отличаются от сменного
        # sales-блока («Карта МПС» = банковские карты 64% наливов, «КР» =
        # локальные топливные карты, тех.отпуски) — без досева 2/3 наливов
        # оставались «не размечено». sort_order 106+ — ПОСЛЕ 'кредит'(103)/
        # 'кред.рубл'(104), иначе паттерн 'кр' перехватил бы «Кредит».
        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_ftx_company_card_dt "
            "ON fuel_transactions (company_id, card, dt) WHERE card IS NOT NULL",
            "INSERT INTO payment_mappings (id, company_id, pattern, channel_code, warehouse_override, sort_order) "
            "SELECT gen_random_uuid(), c.id, v.pattern, v.channel_code, v.warehouse_override, v.sort_order "
            "FROM companies c "
            "CROSS JOIN (VALUES "
            "  ('мпс', 'retail_card', NULL, 106), "
            "  ('кр', 'cards', 'Карты', 107), "
            "  ('мерник', 'writeoff_fuel', NULL, 108), "
            "  ('отпуск бо', 'writeoff_fuel', NULL, 109)"
            ") AS v(pattern, channel_code, warehouse_override, sort_order) "
            "WHERE EXISTS (SELECT 1 FROM payment_mappings m WHERE m.company_id = c.id) "
            "ON CONFLICT (company_id, pattern) DO NOTHING",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.13: имена объектов ЭЗС = свежайшее имя из сессий (волна переименований
        # CPO 01.07.26: 611 «Новая Рига Аутлет Вилладж»→«Новая Рига» и др.; каталог
        # грузился из xlsx до переименования и отстал). Старое имя — в
        # extra_metadata.nameHistory (поиск по нему сохраняется). Идемпотентно:
        # после выравнивания имён — no-op; при новых переименованиях в сессиях
        # подхватит на следующем старте (страховка к обновлению при ingest).
        await conn.execute(__import__("sqlalchemy").text(
            "WITH fresh AS ("
            "  SELECT DISTINCT ON (location_id) location_id, btrim(station_name) AS nm"
            "  FROM charge_sessions"
            "  WHERE location_id IS NOT NULL AND station_name IS NOT NULL"
            "    AND btrim(station_name) <> ''"
            "  ORDER BY location_id, started_at DESC NULLS LAST) "
            "UPDATE service_locations sl SET "
            "  extra_metadata = jsonb_set(coalesce(sl.extra_metadata, '{}'::jsonb), '{nameHistory}',"
            "      coalesce(sl.extra_metadata->'nameHistory', '[]'::jsonb) || to_jsonb(sl.name)),"
            "  name = f.nm "
            "FROM fresh f "
            "WHERE f.location_id = sl.id AND btrim(sl.name) IS DISTINCT FROM f.nm"
        ))

        # v2.14: сводная выработка ЭЗС («ОБЩАЯ_2024-2026», слот obshaya канала
        # реестров) — паспортные атрибуты станции из станционного листа «Общие
        # итоги»; station_dispense_periods создаётся через metadata.create_all.
        for stmt in (
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS location_class VARCHAR(20)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS speed_class VARCHAR(10)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS installed_on VARCHAR(10)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS decommissioned_on VARCHAR(10)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS inventory_number VARCHAR(60)",
            "ALTER TABLE service_locations ADD COLUMN IF NOT EXISTS is_corp BOOLEAN NOT NULL DEFAULT false",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.15: складской учёт оборудования ЭЗС (ezs_equipment_units/_movements,
        # ezs_spare_parts/_stock/_movements — таблицы через metadata.create_all).
        # Здесь — только функциональные уникальные индексы (декларативно не выразить):
        # серийник уникален per company без учёта регистра (пустые не участвуют);
        # имя номенклатуры ЗИП уникально per company без учёта регистра.
        for stmt in (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ezs_unit_serial "
            "ON ezs_equipment_units (company_id, lower(serial_number)) "
            "WHERE serial_number IS NOT NULL AND serial_number <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ezs_spare_name "
            "ON ezs_spare_parts (company_id, lower(name))",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.16: чат (chat_rooms/participants/messages/reactions/folders — через
        # metadata.create_all). Здесь — presence-колонка + поля фазы 2 (закреп,
        # вложения) на существующих таблицах.
        for stmt in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS pinned_message_id UUID",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url TEXT",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_name VARCHAR(500)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_size INTEGER",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.17: контроль дублей номенклатуры (dedup_cards/dedup_ns_bindings/
        # dedup_statuses — новые таблицы через metadata.create_all, ALTER не нужен).

        # v2.18: розничная цена карточки (РС.ЦеныНоменклатуры) для среза рассинхрона.
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE dedup_cards ADD COLUMN IF NOT EXISTS price DOUBLE PRECISION"))

        # v2.19: задания на корректировку дублей (dedup_correction_jobs — новая
        # таблица через metadata.create_all, ALTER не нужен).

        # v2.20: продажи карточки за 30 дн (ОРП) — «продаётся сейчас» для выбора канона.
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE dedup_cards ADD COLUMN IF NOT EXISTS sold_qty DOUBLE PRECISION"))

        # v2.21: документы поставки/возврата оборудования (слой оснований).
        # Таблицы ezs_supply_documents/_lines — через metadata.create_all. Здесь —
        # ссылки приход↔документ на существующих ezs-таблицах + денежная оценка ОС
        # на единице (первоначальная стоимость 07/08 для выгрузки в БП) + индекс
        # реестра «единицы поставки» (create_all не добавляет колонки к готовым таблицам).
        for stmt in (
            "ALTER TABLE ezs_equipment_units ADD COLUMN IF NOT EXISTS supply_id UUID",
            "ALTER TABLE ezs_equipment_units ADD COLUMN IF NOT EXISTS supply_line_id UUID",
            "ALTER TABLE ezs_equipment_units ADD COLUMN IF NOT EXISTS purchase_amount NUMERIC(14,2)",
            "ALTER TABLE ezs_equipment_units ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(14,2)",
            "ALTER TABLE ezs_equipment_movements ADD COLUMN IF NOT EXISTS supply_id UUID",
            "ALTER TABLE ezs_equipment_movements ADD COLUMN IF NOT EXISTS supply_line_id UUID",
            "ALTER TABLE ezs_spare_part_movements ADD COLUMN IF NOT EXISTS supply_id UUID",
            "ALTER TABLE ezs_spare_part_movements ADD COLUMN IF NOT EXISTS supply_line_id UUID",
            "CREATE INDEX IF NOT EXISTS ix_ezs_unit_supply "
            "ON ezs_equipment_units (company_id, supply_id)",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # Часовой пояс региона (смещение от МСК, часов) — для анализа сессий ЭЗС
        # «по местному времени». Заполняется tz_offsets.backfill_region_offsets.
        for stmt in (
            "ALTER TABLE regions ADD COLUMN IF NOT EXISTS msk_offset SMALLINT",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.22: банк ЗУ — воронка подбора недвижимости вместо трёх «листов».
        # Добавляем идентичность площадки (без неё импорт был REPLACE-ALL и стирал
        # историю), нормализованный регион и стадийные поля. Затем переводим
        # legacy-стадии: «Согласованные» лежали в prospect, хотя там договоры на
        # подписи — это конец воронки, а не начало (см. docs/SITES_LAND_BANK_BLUEPRINT.md).
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS stage_since VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS prev_stage VARCHAR(16)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS archive_reason VARCHAR(200)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS cadastral_no VARCHAR(40)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(200)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS region_norm VARCHAR(160)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS region_id UUID",
            "CREATE INDEX IF NOT EXISTS ix_ezs_site_company_dedup "
            "ON ezs_sites (company_id, dedup_key)",
            # prospect = лист «Согласованные» (договор на подписи) → оформление;
            # in_work = лист «ЗУ в работе» (первичные переговоры) → переговоры.
            # Точную стадию внутри активной части проставит ближайший импорт.
            "UPDATE ezs_sites SET stage='contracting' WHERE stage='prospect'",
            "UPDATE ezs_sites SET stage='negotiation' WHERE stage='in_work'",
            "UPDATE ezs_sites SET first_seen_at=COALESCE(first_seen_at, created_at), "
            "last_seen_at=COALESCE(last_seen_at, created_at) WHERE first_seen_at IS NULL",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.23: банк ЗУ — ведение площадки руками (ответственный, следующий шаг,
        # чек-листы гейтов), права на землю и техприсоединение отдельными полями,
        # связь с объектом сети. Таблица событий — через create_all.
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS owner_user_id UUID",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS next_action VARCHAR(300)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS next_action_due VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS last_touch_at TIMESTAMPTZ",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS hold_until VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS gates JSONB",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS manual_fields JSONB",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS control_form VARCHAR(40)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS land_category VARCHAR(80)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS permitted_use VARCHAR(200)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS encumbrances TEXT",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS rent_rate NUMERIC(14,2)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS contract_start VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS contract_end VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS free_power_num DOUBLE PRECISION",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS distance_to_tp_m DOUBLE PRECISION",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS tp_cost NUMERIC(16,2)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS tp_term_months DOUBLE PRECISION",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS location_id UUID",
            "CREATE INDEX IF NOT EXISTS ix_ezs_site_company_owner "
            "ON ezs_sites (company_id, owner_user_id)",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.24: раздел «Проекты» — площадка становится проектом с номером,
        # этапами и документами. Номера выдаём разом всем существующим записям
        # (по дате появления), иначе часть банка останется без идентификатора,
        # которым её можно назвать в переписке.
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS project_no VARCHAR(32)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS title VARCHAR(300)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ezs_site_project_no "
            "ON ezs_sites (company_id, project_no) WHERE project_no IS NOT NULL",
            # Нумерация продолжается ОТ УЖЕ ВЫДАННЫХ номеров, а не с единицы:
            # иначе площадка без номера (такие приносил импорт до v51) получала
            # «ЭЗС-2026-0001», который давно занят, и весь старт падал на
            # uq_ezs_site_project_no — с ним падало всё приложение.
            """
            WITH taken AS (
                SELECT company_id,
                       to_char(COALESCE(first_seen_at, created_at), 'YYYY') AS yr,
                       COALESCE(MAX(NULLIF(split_part(project_no, '-', 3), '')::int), 0) AS mx
                FROM ezs_sites
                WHERE project_no LIKE 'ЭЗС-%'
                GROUP BY 1, 2
            ), numbered AS (
                SELECT id, company_id,
                       to_char(COALESCE(first_seen_at, created_at), 'YYYY') AS yr,
                       row_number() OVER (
                           PARTITION BY company_id, to_char(COALESCE(first_seen_at, created_at), 'YYYY')
                           ORDER BY COALESCE(first_seen_at, created_at), id) AS n
                FROM ezs_sites WHERE project_no IS NULL
            )
            UPDATE ezs_sites s SET project_no = 'ЭЗС-' || numbered.yr || '-' ||
                   lpad((COALESCE(taken.mx, 0) + numbered.n)::text, 4, '0')
            FROM numbered LEFT JOIN taken
              ON taken.company_id = numbered.company_id AND taken.yr = numbered.yr
            WHERE numbered.id = s.id
            """,
            # Субсидия и замыкание на учёт (таблицы ezs_site_docs /
            # ezs_tech_connections / ezs_site_costs создаёт create_all).
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS subsidy_planned BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS parking_spots INTEGER",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS access_24x7 BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS has_lighting BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS has_internet BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS subsidy_amount NUMERIC(16,2)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS commissioned_on VARCHAR(10)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS contract_id UUID",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.25: роль участника — ссылкой на карточку контрагента, а не строкой.
        # Текст остаётся исходником (что написали в файле), ссылка отвечает за «это
        # то же юрлицо, что в договоре». Заполняются сопоставлением (space_links.py),
        # здесь только заводим колонки.
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS owner_counterparty_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS supplier_counterparty_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS contractor_counterparty_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS "
            "grid_operator_counterparty_id UUID REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE ezs_site_equipment ADD COLUMN IF NOT EXISTS "
            "supplier_counterparty_id UUID REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE corporate_clients ADD COLUMN IF NOT EXISTS counterparty_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.26: все 55 обязательных граф «Банка данных ЗУ» (чек-лист согласования
        # ЗУ под ЭЗС, РусГидро). Часть граф уже приезжала в `raw`, но не имела
        # своего поля — значит не считалась, не фильтровалась и не закрывала гейт.
        # Паспорт питающей сети и деньги ТУ идут в карточку присоединения: это её
        # предмет, а не свойство участка.
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS input_price_kwth NUMERIC(12,4)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS smr_cost NUMERIC(16,2)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS long_term_contract BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS has_video BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS has_mobile BOOLEAN",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS owner_contact TEXT",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS source_company VARCHAR(300)",
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS source_person TEXT",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS substation_owner VARCHAR(200)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS line_owner VARCHAR(200)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS transformer_kva VARCHAR(80)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS line_type VARCHAR(120)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS extra_power_possible BOOLEAN",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS transformer_swap_possible BOOLEAN",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS works_cost NUMERIC(16,2)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS total_cost NUMERIC(16,2)",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS applicant_term_months DOUBLE PRECISION",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.27: три сущности вместо одной — площадка (место) / проект (временное
        # предприятие) / объект сети (актив). Таблицу `ezs_projects` создаёт
        # create_all; здесь чиним типы и заводим по проекту на каждую площадку,
        # чтобы ничего не потерялось при переходе.
        for stmt in (
            # `service_locations.id` — строковый nanoid: колонка UUID делала связь
            # проекта с объектом физически невозможной (значений 0, приведение
            # безопасно).
            "ALTER TABLE ezs_sites ALTER COLUMN location_id TYPE VARCHAR(40) "
            "USING location_id::text",
            # Проект на каждую существующую площадку: номер, стадия и ведение
            # переезжают как есть, тип — новое строительство.
            """
            INSERT INTO ezs_projects (
                id, company_id, site_id, location_id, kind, project_no, title,
                stage, stage_since, prev_stage, owner_user_id, next_action,
                next_action_due, last_touch_at, hold_until, gates, commissioned_on,
                contract_id, created_at, updated_at)
            SELECT gen_random_uuid(), s.company_id, s.id, s.location_id, 'new_build',
                   s.project_no, s.title, s.stage, s.stage_since, s.prev_stage,
                   s.owner_user_id, s.next_action, s.next_action_due, s.last_touch_at,
                   s.hold_until, s.gates, s.commissioned_on, s.contract_id,
                   COALESCE(s.created_at, now()), s.updated_at
            FROM ezs_sites s
            WHERE NOT EXISTS (SELECT 1 FROM ezs_projects p WHERE p.site_id = s.id)
            """,
            # Спутники проекта знают свой проект: пока связь идёт через площадку,
            # второй проект на том же месте склеился бы с первым.
            "ALTER TABLE ezs_site_docs ADD COLUMN IF NOT EXISTS project_id UUID "
            "REFERENCES ezs_projects(id) ON DELETE CASCADE",
            "ALTER TABLE ezs_tech_connections ADD COLUMN IF NOT EXISTS project_id UUID "
            "REFERENCES ezs_projects(id) ON DELETE CASCADE",
            "ALTER TABLE ezs_site_equipment ADD COLUMN IF NOT EXISTS project_id UUID "
            "REFERENCES ezs_projects(id) ON DELETE CASCADE",
            "ALTER TABLE ezs_site_costs ADD COLUMN IF NOT EXISTS project_id UUID "
            "REFERENCES ezs_projects(id) ON DELETE CASCADE",
            "ALTER TABLE ezs_site_events ADD COLUMN IF NOT EXISTS project_id UUID "
            "REFERENCES ezs_projects(id) ON DELETE CASCADE",
            # Существующие спутники относятся к первому (единственному) проекту площадки.
            "UPDATE ezs_site_docs d SET project_id = p.id FROM ezs_projects p "
            "WHERE p.site_id = d.site_id AND d.project_id IS NULL",
            "UPDATE ezs_tech_connections t SET project_id = p.id FROM ezs_projects p "
            "WHERE p.site_id = t.site_id AND t.project_id IS NULL",
            "UPDATE ezs_site_equipment e SET project_id = p.id FROM ezs_projects p "
            "WHERE p.site_id = e.site_id AND e.project_id IS NULL",
            "UPDATE ezs_site_costs c SET project_id = p.id FROM ezs_projects p "
            "WHERE p.site_id = c.site_id AND c.project_id IS NULL",
            "UPDATE ezs_site_events ev SET project_id = p.id FROM ezs_projects p "
            "WHERE p.site_id = ev.site_id AND ev.project_id IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ezs_project_no "
            "ON ezs_projects (company_id, project_no) WHERE project_no IS NOT NULL",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.28: «Инфо» — знание пространства (таблицы создаёт create_all).
        # Полнотекстовый поиск по-русски: заголовок весомее тела, теги — третьим
        # весом. Без него поиск по 500 статьям превращается в LIKE по всей базе.
        for stmt in (
            "ALTER TABLE info_articles ADD COLUMN IF NOT EXISTS search_tsv tsvector",
            """
            CREATE OR REPLACE FUNCTION info_articles_tsv_update() RETURNS trigger AS $$
            BEGIN
              NEW.search_tsv :=
                setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('russian', coalesce(NEW.summary, '')), 'A') ||
                setweight(to_tsvector('russian', coalesce(NEW.body_md, '')), 'B') ||
                setweight(to_tsvector('russian', coalesce(NEW.doc_number, '')), 'C');
              RETURN NEW;
            END $$ LANGUAGE plpgsql
            """,
            "DROP TRIGGER IF EXISTS info_articles_tsv_trg ON info_articles",
            "CREATE TRIGGER info_articles_tsv_trg BEFORE INSERT OR UPDATE ON info_articles "
            "FOR EACH ROW EXECUTE FUNCTION info_articles_tsv_update()",
            "CREATE INDEX IF NOT EXISTS ix_info_articles_tsv ON info_articles USING GIN(search_tsv)",
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
