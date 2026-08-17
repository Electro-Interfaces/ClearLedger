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


STORE_RECEIPT_MIGRATION_DDL = (
    "DROP TRIGGER IF EXISTS store_receipt_stock_movement_immutable_trg "
    "ON store_receipt_stock_movements",
    "DROP TRIGGER IF EXISTS store_receipt_accounting_revision_trg ON store_receipts",
    "ALTER TABLE store_receipts ALTER COLUMN station_id DROP NOT NULL",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS services JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64)",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS supplier_id UUID "
    "REFERENCES counterparties(id) ON DELETE RESTRICT",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS contract_id UUID "
    "REFERENCES contracts(id) ON DELETE RESTRICT",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS organization_id UUID "
    "REFERENCES organizations(id) ON DELETE RESTRICT",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS warehouse_id UUID "
    "REFERENCES warehouses(id) ON DELETE RESTRICT",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS supplier_snapshot JSONB",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS contract_snapshot JSONB",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS organization_snapshot JSONB",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS warehouse_snapshot JSONB",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS accounting_status "
    "VARCHAR(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS accounting_error TEXT",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS accounting_revision "
    "INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS content_hash CHAR(64)",
    "ALTER TABLE space_inbound_keys ADD COLUMN IF NOT EXISTS station_id INTEGER",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_space_inbound_key_station_active "
    "ON space_inbound_keys (company_id, station_id) "
    "WHERE station_id IS NOT NULL AND revoked_at IS NULL",
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            -- current_schema(), а не 'public': в пространстве Ядро живёт в схеме
            -- `core` (базы Ядра и Поддержки сведены). С жёстким 'public' проверка
            -- ничего не находит, ALTER идёт по search_path и падает
            -- DuplicateColumnError — бэкенд не поднимается вовсе.
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'counterparties'
               AND column_name = 'lifecycle_status'
        ) THEN
            ALTER TABLE counterparties ADD COLUMN lifecycle_status
                VARCHAR(20) NOT NULL DEFAULT 'draft';
            UPDATE counterparties SET lifecycle_status = 'verified'
             WHERE external_ref IS NOT NULL AND btrim(external_ref) <> ''
               AND btrim(inn) <> '' AND btrim(name) <> '';
        END IF;
    END $$
    """,
    "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS organization_id UUID "
    "REFERENCES organizations(id) ON DELETE RESTRICT",
    "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS station_id INTEGER",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_store_receipt_accounting_status') THEN
            ALTER TABLE store_receipts ADD CONSTRAINT ck_store_receipt_accounting_status
            CHECK (accounting_status IN ('pending','needs_review','ready'));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_store_receipt_accounting_revision') THEN
            ALTER TABLE store_receipts ADD CONSTRAINT ck_store_receipt_accounting_revision
            CHECK (accounting_revision >= 0);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_store_receipt_content_hash') THEN
            ALTER TABLE store_receipts ADD CONSTRAINT ck_store_receipt_content_hash
            CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_counterparty_lifecycle_status') THEN
            ALTER TABLE counterparties ADD CONSTRAINT ck_counterparty_lifecycle_status
            CHECK (lifecycle_status IN ('draft','verified','blocked','archived'));
        END IF;
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS ix_store_receipts_supplier ON store_receipts (company_id, supplier_id)",
    "CREATE INDEX IF NOT EXISTS ix_store_receipts_contract ON store_receipts (company_id, contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_store_receipts_organization "
    "ON store_receipts (company_id, organization_id)",
    "CREATE INDEX IF NOT EXISTS ix_store_receipts_warehouse "
    "ON store_receipts (company_id, warehouse_id)",
    "CREATE INDEX IF NOT EXISTS ix_warehouses_accounting_scope "
    "ON warehouses (company_id, organization_id, station_id)",
    "ALTER TABLE store_receipts DROP CONSTRAINT IF EXISTS store_receipts_source_uuid_key",
    "DROP INDEX IF EXISTS ix_store_receipts_source_uuid",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_receipts_company_source "
    "ON store_receipts (company_id, source_uuid) WHERE source_uuid IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_receipts_company_dedup "
    "ON store_receipts (company_id, dedup_key) WHERE dedup_key IS NOT NULL",
    "ALTER TABLE edge_downlink ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(200)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_edge_downlink_company_idempotency "
    "ON edge_downlink (company_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
    "ALTER TABLE IF EXISTS edge.partner ADD COLUMN IF NOT EXISTS external_uuid UUID",
    """
    DO $$ BEGIN
        IF to_regclass('edge.partner') IS NOT NULL THEN
            EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_edge_partner_company_external_uuid '
                    'ON edge.partner (company_id, external_uuid) WHERE external_uuid IS NOT NULL';
        END IF;
    END $$
    """,
    """
    DO $$ BEGIN
        IF to_regclass('edge.partner') IS NOT NULL THEN
            EXECUTE $sql$
                UPDATE edge.partner p
                   SET external_uuid = c.id
                  FROM counterparties c
                 WHERE p.external_uuid IS NULL
                   AND c.company_id = p.company_id
                   AND regexp_replace(c.inn, '\\D', '', 'g') =
                       regexp_replace(coalesce(p.inn, ''), '\\D', '', 'g')
                   AND regexp_replace(coalesce(p.inn, ''), '\\D', '', 'g') <> ''
                   AND (SELECT count(*) FROM counterparties c2
                         WHERE c2.company_id = p.company_id
                           AND regexp_replace(c2.inn, '\\D', '', 'g') =
                               regexp_replace(coalesce(p.inn, ''), '\\D', '', 'g')) = 1
                   AND NOT EXISTS (SELECT 1 FROM edge.partner p2
                                    WHERE p2.company_id = p.company_id
                                      AND p2.external_uuid = c.id)
            $sql$;
        END IF;
    END $$
    """,
    """
    CREATE TABLE IF NOT EXISTS store_receipt_stock_movements (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        receipt_id UUID NOT NULL REFERENCES store_receipts(id) ON DELETE RESTRICT,
        reversal_of_id UUID REFERENCES store_receipt_stock_movements(id) ON DELETE RESTRICT,
        allocation_id VARCHAR(64),
        line_id UUID NOT NULL,
        line_index INTEGER NOT NULL,
        station_id INTEGER,
        warehouse_id UUID REFERENCES warehouses(id) ON DELETE RESTRICT,
        warehouse VARCHAR(200) NOT NULL,
        item_key VARCHAR(200) NOT NULL,
        item_uuid VARCHAR(64),
        barcode VARCHAR(100),
        quantity NUMERIC(16,3) NOT NULL,
        unit_cost NUMERIC(16,4) NOT NULL DEFAULT 0,
        amount NUMERIC(16,2) NOT NULL DEFAULT 0,
        kind VARCHAR(40) NOT NULL,
        idempotency_key VARCHAR(200) NOT NULL,
        created_by UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_store_receipt_stock_movement_key
            UNIQUE (company_id, idempotency_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_store_receipt_stock_movement_receipt "
    "ON store_receipt_stock_movements (receipt_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_store_receipt_stock_movement_balance "
    "ON store_receipt_stock_movements (company_id, warehouse, item_key, created_at)",
    "ALTER TABLE store_receipt_stock_movements ADD COLUMN IF NOT EXISTS line_id UUID",
    "ALTER TABLE store_receipt_stock_movements ADD COLUMN IF NOT EXISTS warehouse_id UUID "
    "REFERENCES warehouses(id) ON DELETE RESTRICT",
    """
    UPDATE store_receipts r
       SET accounting_status = 'needs_review',
           accounting_error = 'Некорректный legacy line_id требует ручной проверки'
     WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements(r.lines) line
         WHERE line ? 'line_id'
           AND NOT (line->>'line_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
     ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(r.services) service
         WHERE service ? 'line_id'
           AND NOT (service->>'line_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
     )
    """,
    """
    UPDATE store_receipts r
       SET lines = filled.value
      FROM (
        SELECT source.id,
               jsonb_agg(
                   CASE WHEN element.value->>'line_id' ~*
                                  '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN element.value
                        ELSE jsonb_set(
                            element.value, '{line_id}',
                            to_jsonb(md5(
                                source.id::text || '|goods|' ||
                                coalesce(nullif(element.value->>'Key', ''),
                                         nullif(element.value->>'Ключ', ''),
                                         nullif(element.value->>'ИдентификаторСтроки', ''),
                                         (element.value - 'qty_expected' - 'qty_fact' -
                                          'amount' - 'vat_amount' - 'price' - 'vat_rate' -
                                          'retail_price' - 'markup' - 'mark_codes' -
                                          'upd_codes' - 'pack_codes')::text)
                            )::uuid::text), true)
                   END ORDER BY element.ordinality
               ) AS value
          FROM store_receipts source
          CROSS JOIN LATERAL jsonb_array_elements(source.lines)
               WITH ORDINALITY AS element(value, ordinality)
         GROUP BY source.id
      ) filled
     WHERE filled.id = r.id
       AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.lines) line
                    WHERE NOT line ? 'line_id'
                       OR NOT (line->>'line_id' ~*
                           '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
    """,
    """
    UPDATE store_receipts r
       SET services = filled.value
      FROM (
        SELECT source.id,
               jsonb_agg(
                   CASE WHEN element.value->>'line_id' ~*
                                  '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN element.value
                        ELSE jsonb_set(
                            element.value, '{line_id}',
                            to_jsonb(md5(
                                source.id::text || '|service|' ||
                                coalesce(nullif(element.value->>'Key', ''),
                                         nullif(element.value->>'Ключ', ''),
                                         nullif(element.value->>'ИдентификаторСтроки', ''),
                                         (element.value - 'amount' - 'vat_amount' -
                                          'vat_rate' - 'into_cost')::text)
                            )::uuid::text), true)
                   END ORDER BY element.ordinality
               ) AS value
          FROM store_receipts source
          CROSS JOIN LATERAL jsonb_array_elements(source.services)
               WITH ORDINALITY AS element(value, ordinality)
         GROUP BY source.id
      ) filled
     WHERE filled.id = r.id
       AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.services) service
                    WHERE NOT service ? 'line_id'
                       OR NOT (service->>'line_id' ~*
                           '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
    """,
    """
    UPDATE store_receipts r
       SET accounting_status = 'needs_review',
           accounting_error = 'Неразличимые legacy-строки требуют ручного line_id'
     WHERE EXISTS (
        SELECT 1
          FROM jsonb_array_elements(r.lines) line
         GROUP BY line->>'line_id'
        HAVING count(*) > 1
     ) OR EXISTS (
        SELECT 1
          FROM jsonb_array_elements(r.services) service
         GROUP BY service->>'line_id'
        HAVING count(*) > 1
     )
    """,
    """
    UPDATE store_receipt_stock_movements movement
       SET line_id = (receipt.lines->movement.line_index->>'line_id')::uuid
      FROM store_receipts receipt
     WHERE movement.receipt_id = receipt.id
       AND movement.line_id IS NULL
       AND receipt.lines->movement.line_index->>'line_id' ~*
           '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    """,
    # Двоеточие в литерале удвоено. SQLAlchemy разбирает «:имя» как подстановку
    # даже внутри строковой константы SQL, и приложение падало на старте с
    # «A value is required for bind parameter 'legacy'»: миграции идут до
    # готовности воркера, поэтому стек не поднимался вовсе. Сама строка здесь —
    # только соль для md5, её вид ни на что не влияет.
    "UPDATE store_receipt_stock_movements SET line_id = "
    "md5(receipt_id::text || '::legacy-movement::' || line_index::text)::uuid "
    "WHERE line_id IS NULL",
    "ALTER TABLE store_receipt_stock_movements ALTER COLUMN line_id SET NOT NULL",
    "UPDATE store_receipt_stock_movements m SET warehouse_id = r.warehouse_id "
    "FROM store_receipts r WHERE m.receipt_id = r.id AND m.warehouse_id IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_store_receipt_stock_movement_canonical_balance "
    "ON store_receipt_stock_movements (company_id, warehouse_id, item_key, created_at)",
    """
    CREATE OR REPLACE FUNCTION protect_store_receipt_stock_movement()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'store receipt stock movements are append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS store_receipt_stock_movement_immutable_trg "
    "ON store_receipt_stock_movements",
    """
    CREATE TRIGGER store_receipt_stock_movement_immutable_trg
    BEFORE UPDATE OR DELETE ON store_receipt_stock_movements
    FOR EACH ROW EXECUTE FUNCTION protect_store_receipt_stock_movement()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_store_receipt_accounting_revision()
    RETURNS trigger AS $$
    BEGIN
        IF OLD.status IN ('accepted', 'reversed')
           AND (NEW.evidence IS DISTINCT FROM OLD.evidence
                OR NEW.lines IS DISTINCT FROM OLD.lines
                OR NEW.services IS DISTINCT FROM OLD.services
                OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                OR NEW.vat_amount IS DISTINCT FROM OLD.vat_amount) THEN
            RAISE EXCEPTION 'accepted store receipt evidence is immutable';
        END IF;
        IF NEW.accounting_revision < OLD.accounting_revision THEN
            RAISE EXCEPTION 'store receipt accounting revision cannot decrease';
        END IF;
        IF (NEW.content_hash IS DISTINCT FROM OLD.content_hash
            OR NEW.supplier_snapshot IS DISTINCT FROM OLD.supplier_snapshot
            OR NEW.contract_snapshot IS DISTINCT FROM OLD.contract_snapshot
            OR NEW.organization_snapshot IS DISTINCT FROM OLD.organization_snapshot
            OR NEW.warehouse_snapshot IS DISTINCT FROM OLD.warehouse_snapshot)
           AND NEW.accounting_revision <= OLD.accounting_revision
           AND OLD.accounting_revision > 0 THEN
            RAISE EXCEPTION 'accounting snapshot change requires a new revision';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS store_receipt_accounting_revision_trg ON store_receipts",
    """
    CREATE TRIGGER store_receipt_accounting_revision_trg
    BEFORE UPDATE ON store_receipts
    FOR EACH ROW EXECUTE FUNCTION protect_store_receipt_accounting_revision()
    """,
    """
    CREATE TABLE IF NOT EXISTS edge_packet_revisions (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        edge_packet_id UUID NOT NULL REFERENCES edge_packets(id) ON DELETE RESTRICT,
        packet_uuid VARCHAR(64) NOT NULL,
        content_hash CHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        wire_size_bytes INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'received',
        error TEXT,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_edge_packet_revision_content_hash
            CHECK (content_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_edge_packet_revision_status
            CHECK (status IN ('received','needs_review')),
        CONSTRAINT uq_edge_packet_revision_content
            UNIQUE (company_id, packet_uuid, content_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_edge_packet_revision_packet "
    "ON edge_packet_revisions (edge_packet_id, received_at)",
    """
    CREATE TABLE IF NOT EXISTS edge_packet_processing_issues (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        edge_packet_id UUID NOT NULL REFERENCES edge_packets(id) ON DELETE RESTRICT,
        revision_id UUID NOT NULL REFERENCES edge_packet_revisions(id) ON DELETE RESTRICT,
        packet_uuid VARCHAR(64) NOT NULL,
        content_hash CHAR(64) NOT NULL,
        phase VARCHAR(30) NOT NULL DEFAULT 'derived',
        status VARCHAR(20) NOT NULL DEFAULT 'needs_review',
        error TEXT NOT NULL,
        error_hash CHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_edge_packet_issue_content_hash
            CHECK (content_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_edge_packet_issue_error_hash
            CHECK (error_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_edge_packet_issue_status CHECK (status = 'needs_review'),
        CONSTRAINT uq_edge_packet_processing_issue_error
            UNIQUE (company_id, packet_uuid, content_hash, error_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_edge_packet_issue_packet "
    "ON edge_packet_processing_issues (edge_packet_id, created_at)",
    """
    CREATE OR REPLACE FUNCTION protect_edge_packet_revision()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'edge packet raw revisions are append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS edge_packet_revision_immutable_trg ON edge_packet_revisions",
    """
    CREATE TRIGGER edge_packet_revision_immutable_trg
    BEFORE UPDATE OR DELETE ON edge_packet_revisions
    FOR EACH ROW EXECUTE FUNCTION protect_edge_packet_revision()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_edge_packet_processing_issue()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'edge packet processing issues are append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS edge_packet_processing_issue_immutable_trg "
    "ON edge_packet_processing_issues",
    """
    CREATE TRIGGER edge_packet_processing_issue_immutable_trg
    BEFORE UPDATE OR DELETE ON edge_packet_processing_issues
    FOR EACH ROW EXECUTE FUNCTION protect_edge_packet_processing_issue()
    """,
)


ACCOUNTING_EGRESS_MIGRATION_DDL = (
    """
    CREATE OR REPLACE FUNCTION reject_accounting_source_policy_overlap()
    RETURNS trigger AS $$
    BEGIN
        IF NEW.effective_to IS NOT NULL AND NEW.effective_to <= NEW.effective_from THEN
            RAISE EXCEPTION 'accounting source policy interval must be [from, to)';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(
            NEW.company_id::text || ':' || NEW.station_id::text || ':' || NEW.policy_group,
            0
        ));
        IF EXISTS (
            SELECT 1
              FROM accounting_source_policies p
             WHERE p.company_id = NEW.company_id
               AND p.station_id = NEW.station_id
               AND p.policy_group = NEW.policy_group
               AND p.id <> NEW.id
               AND p.effective_from < COALESCE(NEW.effective_to, 'infinity'::timestamptz)
               AND NEW.effective_from < COALESCE(p.effective_to, 'infinity'::timestamptz)
        ) THEN
            RAISE EXCEPTION 'overlapping accounting source policy interval';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS accounting_source_policy_overlap_trg ON accounting_source_policies",
    """
    CREATE TRIGGER accounting_source_policy_overlap_trg
    BEFORE INSERT OR UPDATE ON accounting_source_policies
    FOR EACH ROW EXECUTE FUNCTION reject_accounting_source_policy_overlap()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_cutover_manifest_payload()
    RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                OLD.company_id::text || ':' || OLD.station_id::text || ':' || OLD.policy_group,
                0
            ));
        ELSE
            PERFORM pg_advisory_xact_lock(hashtextextended(
                NEW.company_id::text || ':' || NEW.station_id::text || ':' || NEW.policy_group,
                0
            ));
        END IF;
        IF TG_OP = 'INSERT' THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'cutover manifest is immutable';
        END IF;
        IF NEW.policy_id IS DISTINCT FROM OLD.policy_id
           OR NEW.company_id IS DISTINCT FROM OLD.company_id
           OR NEW.station_id IS DISTINCT FROM OLD.station_id
           OR NEW.policy_group IS DISTINCT FROM OLD.policy_group
           OR NEW.revision IS DISTINCT FROM OLD.revision
           OR NEW.canonical_payload IS DISTINCT FROM OLD.canonical_payload
           OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash
           OR NEW.approvals IS DISTINCT FROM OLD.approvals
           OR NEW.operational_cutover_at IS DISTINCT FROM OLD.operational_cutover_at
           OR NEW.accounting_transport_cutover_at IS DISTINCT FROM OLD.accounting_transport_cutover_at
           OR NEW.late_arrival_until IS DISTINCT FROM OLD.late_arrival_until
           OR NEW.arm_deadline IS DISTINCT FROM OLD.arm_deadline THEN
            RAISE EXCEPTION 'cutover manifest payload is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS cutover_manifest_immutable_trg ON cutover_manifests",
    """
    CREATE TRIGGER cutover_manifest_immutable_trg
    BEFORE INSERT OR UPDATE OR DELETE ON cutover_manifests
    FOR EACH ROW EXECUTE FUNCTION protect_cutover_manifest_payload()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_accounting_shadow_result()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'accounting shadow result is immutable';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS accounting_shadow_result_immutable_trg ON accounting_shadow_results",
    """
    CREATE TRIGGER accounting_shadow_result_immutable_trg
    BEFORE UPDATE OR DELETE ON accounting_shadow_results
    FOR EACH ROW EXECUTE FUNCTION protect_accounting_shadow_result()
    """,
)


ACCOUNTING_REVISION_MIGRATION_DDL = (
    "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS document_id UUID",
    "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS revision INTEGER",
    "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS content_hash CHAR(64)",
    "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS fact_origin VARCHAR(20)",
    "ALTER TABLE data_entries ADD COLUMN IF NOT EXISTS supersedes_entry_id UUID",
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'fk_data_entry_supersedes'
        ) THEN
            ALTER TABLE data_entries
            ADD CONSTRAINT fk_data_entry_supersedes
            FOREIGN KEY (supersedes_entry_id) REFERENCES data_entries(id) ON DELETE RESTRICT;
        END IF;
    END $$
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_entry_document_revision "
    "ON data_entries(company_id, document_id, revision) "
    "WHERE document_id IS NOT NULL",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS packet_uuid UUID",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS revision INTEGER",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS contract_version VARCHAR(10)",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS content_hash CHAR(64)",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS fact_origin VARCHAR(20)",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS transport_producer VARCHAR(30)",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS attempt_id UUID",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS ack_payload JSONB",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS component_result JSONB",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS error_code VARCHAR(80)",
    "ALTER TABLE export_packets ADD COLUMN IF NOT EXISTS error_detail TEXT",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_data_entry_revision_positive') THEN
            ALTER TABLE data_entries ADD CONSTRAINT ck_data_entry_revision_positive
            CHECK (revision IS NULL OR revision > 0) NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_data_entry_content_hash') THEN
            ALTER TABLE data_entries ADD CONSTRAINT ck_data_entry_content_hash
            CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$') NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_data_entry_fact_origin') THEN
            ALTER TABLE data_entries ADD CONSTRAINT ck_data_entry_fact_origin
            CHECK (fact_origin IS NULL OR fact_origin IN
                   ('edge','store','onec_legacy','edo','cash')) NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_export_packet_revision_positive') THEN
            ALTER TABLE export_packets ADD CONSTRAINT ck_export_packet_revision_positive
            CHECK (revision IS NULL OR revision > 0) NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_export_packet_content_hash') THEN
            ALTER TABLE export_packets ADD CONSTRAINT ck_export_packet_content_hash
            CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$') NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_export_packet_fact_origin') THEN
            ALTER TABLE export_packets ADD CONSTRAINT ck_export_packet_fact_origin
            CHECK (fact_origin IS NULL OR fact_origin IN
                   ('edge','store','onec_legacy','edo','cash')) NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'ck_export_packet_accounting_contract') THEN
            ALTER TABLE export_packets ADD CONSTRAINT ck_export_packet_accounting_contract
            CHECK (
                kind NOT IN ('food_accounting_group','store_accounting_group') OR (
                    packet_uuid IS NOT NULL AND revision IS NOT NULL
                    AND contract_version IS NOT NULL AND content_hash IS NOT NULL
                    AND fact_origin IS NOT NULL AND transport_producer IS NOT NULL
                    AND status IN ('draft','validated','queued','retry_wait','leased',
                                   'sent_waiting_ack','accepted','rejected','needs_review')
                )
            ) NOT VALID;
        END IF;
    END $$
    """,
    "DROP INDEX IF EXISTS uq_export_packets_active_idem",
    """
    CREATE UNIQUE INDEX uq_export_packets_active_idem
    ON export_packets(company_id, idem_key)
    WHERE idem_key IS NOT NULL
      AND status <> 'rejected'
      AND kind NOT IN ('food_accounting_group', 'store_accounting_group')
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_export_packets_accounting_revision
    ON export_packets(company_id, packet_uuid, revision)
    WHERE kind IN ('food_accounting_group', 'store_accounting_group')
    """,
    """
    CREATE OR REPLACE FUNCTION protect_canonical_data_entry()
    RETURNS trigger AS $$
    DECLARE
        latest_id UUID;
        latest_revision INTEGER;
        latest_hash CHAR(64);
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.document_id IS NOT NULL THEN
                RAISE EXCEPTION 'canonical data entry is append-only';
            END IF;
            RETURN OLD;
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.document_id IS NOT NULL AND (
                NEW.layer <> 'clean'
                OR NEW.revision IS NULL OR NEW.revision <= 0
                OR NEW.content_hash IS NULL
                OR NEW.content_hash !~ '^[0-9a-f]{64}$'
                OR NEW.fact_origin NOT IN ('edge','store','onec_legacy','edo','cash')
            ) THEN
                RAISE EXCEPTION 'invalid canonical data entry';
            END IF;
            IF NEW.document_id IS NOT NULL THEN
                PERFORM pg_advisory_xact_lock(hashtextextended(
                    'canonical-fact:' || NEW.company_id::text || ':' || NEW.document_id::text,
                    0
                ));
                SELECT d.id, d.revision, d.content_hash
                  INTO latest_id, latest_revision, latest_hash
                  FROM data_entries d
                 WHERE d.company_id = NEW.company_id
                   AND d.document_id = NEW.document_id
                 ORDER BY d.revision DESC
                 LIMIT 1
                 FOR UPDATE;
                IF latest_id IS NULL THEN
                    IF NEW.supersedes_entry_id IS NOT NULL THEN
                        RAISE EXCEPTION 'first canonical revision cannot supersede a row';
                    END IF;
                ELSE
                    IF NEW.content_hash = latest_hash THEN
                        RAISE EXCEPTION 'canonical content hash already exists';
                    END IF;
                    IF NEW.revision <= latest_revision THEN
                        RAISE EXCEPTION 'canonical revision must increase';
                    END IF;
                    IF NEW.supersedes_entry_id IS DISTINCT FROM latest_id THEN
                        RAISE EXCEPTION 'canonical revision must supersede latest row';
                    END IF;
                    UPDATE data_entries
                       SET status = 'superseded'
                     WHERE id = latest_id AND status <> 'superseded';
                END IF;
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.document_id IS NULL AND NEW.document_id IS NULL THEN
            RETURN NEW;
        END IF;
        IF OLD.document_id IS NULL OR NEW.document_id IS NULL THEN
            RAISE EXCEPTION 'canonical identity cannot be attached or removed in-place';
        END IF;
        IF NEW.title IS DISTINCT FROM OLD.title
           OR NEW.category_id IS DISTINCT FROM OLD.category_id
           OR NEW.subcategory_id IS DISTINCT FROM OLD.subcategory_id
           OR NEW.doc_type_id IS DISTINCT FROM OLD.doc_type_id
           OR NEW.company_id IS DISTINCT FROM OLD.company_id
           OR NEW.source IS DISTINCT FROM OLD.source
           OR NEW.source_label IS DISTINCT FROM OLD.source_label
           OR NEW.file_url IS DISTINCT FROM OLD.file_url
           OR NEW.file_type IS DISTINCT FROM OLD.file_type
           OR NEW.file_size IS DISTINCT FROM OLD.file_size
           OR NEW.metadata IS DISTINCT FROM OLD.metadata
           OR NEW.ocr_data IS DISTINCT FROM OLD.ocr_data
           OR NEW.source_id IS DISTINCT FROM OLD.source_id
           OR NEW.channel_id IS DISTINCT FROM OLD.channel_id
           OR NEW.layer IS DISTINCT FROM OLD.layer
           OR NEW.derived_from_entry_id IS DISTINCT FROM OLD.derived_from_entry_id
           OR NEW.document_id IS DISTINCT FROM OLD.document_id
           OR NEW.revision IS DISTINCT FROM OLD.revision
           OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
           OR NEW.fact_origin IS DISTINCT FROM OLD.fact_origin
           OR NEW.supersedes_entry_id IS DISTINCT FROM OLD.supersedes_entry_id THEN
            RAISE EXCEPTION 'canonical data entry payload is immutable';
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status
           AND (NEW.status <> 'superseded' OR OLD.status = 'superseded') THEN
            RAISE EXCEPTION 'invalid canonical data entry status transition';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS canonical_data_entry_guard_trg ON data_entries",
    """
    CREATE TRIGGER canonical_data_entry_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON data_entries
    FOR EACH ROW EXECUTE FUNCTION protect_canonical_data_entry()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_accounting_export_packet()
    RETURNS trigger AS $$
    DECLARE
        latest_revision INTEGER;
        latest_kind VARCHAR(30);
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.kind IN ('food_accounting_group', 'store_accounting_group') THEN
                RAISE EXCEPTION 'accounting outbox is append-only';
            END IF;
            RETURN OLD;
        END IF;
        IF TG_OP = 'UPDATE'
           AND NEW.kind IS DISTINCT FROM OLD.kind
           AND (NEW.kind IN ('food_accounting_group', 'store_accounting_group')
                OR OLD.kind IN ('food_accounting_group', 'store_accounting_group')) THEN
            RAISE EXCEPTION 'accounting outbox kind is immutable';
        END IF;
        IF NEW.kind NOT IN ('food_accounting_group', 'store_accounting_group') THEN
            RETURN NEW;
        END IF;
        IF NEW.packet_uuid IS NULL OR NEW.revision IS NULL OR NEW.revision <= 0
           OR NEW.contract_version IS NULL
           OR NEW.content_hash IS NULL OR NEW.content_hash !~ '^[0-9a-f]{64}$'
           OR NEW.fact_origin NOT IN ('edge','store','onec_legacy','edo','cash')
           OR NEW.transport_producer IS NULL THEN
            RAISE EXCEPTION 'invalid accounting outbox contract';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'draft' THEN
                RAISE EXCEPTION 'accounting outbox must start in draft';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'accounting-outbox:' || NEW.company_id::text || ':' || NEW.packet_uuid::text,
                0
            ));
            IF EXISTS (
                SELECT 1 FROM export_packets p
                 WHERE p.company_id = NEW.company_id
                   AND p.packet_uuid = NEW.packet_uuid
                   AND p.kind IN ('food_accounting_group', 'store_accounting_group')
                   AND p.content_hash = NEW.content_hash
            ) THEN
                RAISE EXCEPTION 'accounting packet hash already exists';
            END IF;
            SELECT p.revision, p.kind
              INTO latest_revision, latest_kind
              FROM export_packets p
             WHERE p.company_id = NEW.company_id
               AND p.packet_uuid = NEW.packet_uuid
               AND p.kind IN ('food_accounting_group', 'store_accounting_group')
             ORDER BY p.revision DESC
             LIMIT 1
             FOR UPDATE;
            IF latest_revision IS NOT NULL AND NEW.revision <= latest_revision THEN
                RAISE EXCEPTION 'accounting packet revision must increase';
            END IF;
            IF latest_kind IS NOT NULL AND NEW.kind <> latest_kind THEN
                RAISE EXCEPTION 'accounting packet kind cannot change between revisions';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status = 'validated')
            OR (OLD.status = 'validated' AND NEW.status IN ('queued','retry_wait'))
            OR (OLD.status IN ('queued','retry_wait') AND NEW.status = 'leased')
            OR (OLD.status = 'leased' AND NEW.status IN ('sent_waiting_ack','retry_wait'))
            OR (OLD.status = 'sent_waiting_ack'
                AND NEW.status IN ('accepted','rejected','needs_review'))
        ) THEN
            RAISE EXCEPTION 'invalid accounting outbox status transition: % -> %',
                OLD.status, NEW.status;
        END IF;
        IF OLD.status <> 'draft' AND (
            NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.idem_key IS DISTINCT FROM OLD.idem_key
            OR NEW.source_entry_ids IS DISTINCT FROM OLD.source_entry_ids
            OR NEW.payload IS DISTINCT FROM OLD.payload
            OR NEW.packet_uuid IS DISTINCT FROM OLD.packet_uuid
            OR NEW.revision IS DISTINCT FROM OLD.revision
            OR NEW.contract_version IS DISTINCT FROM OLD.contract_version
            OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
            OR NEW.fact_origin IS DISTINCT FROM OLD.fact_origin
            OR NEW.transport_producer IS DISTINCT FROM OLD.transport_producer
        ) THEN
            RAISE EXCEPTION 'validated accounting outbox core is immutable';
        END IF;
        IF NEW.status = 'leased'
           AND (NEW.attempt_id IS NULL OR NEW.lease_until IS NULL) THEN
            RAISE EXCEPTION 'leased accounting outbox requires attempt and lease';
        END IF;
        IF OLD.status IN ('accepted','rejected','needs_review') AND (
            NEW.status IS DISTINCT FROM OLD.status
            OR NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
            OR NEW.lease_until IS DISTINCT FROM OLD.lease_until
            OR NEW.sent_at IS DISTINCT FROM OLD.sent_at
            OR NEW.acked_at IS DISTINCT FROM OLD.acked_at
            OR NEW.ack_payload IS DISTINCT FROM OLD.ack_payload
            OR NEW.component_result IS DISTINCT FROM OLD.component_result
            OR NEW.error_code IS DISTINCT FROM OLD.error_code
            OR NEW.error_detail IS DISTINCT FROM OLD.error_detail
            OR NEW.reject_reason IS DISTINCT FROM OLD.reject_reason
            OR NEW.target_doc_id IS DISTINCT FROM OLD.target_doc_id
        ) THEN
            RAISE EXCEPTION 'terminal accounting outbox result is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS accounting_export_packet_guard_trg ON export_packets",
    """
    CREATE TRIGGER accounting_export_packet_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON export_packets
    FOR EACH ROW EXECUTE FUNCTION protect_accounting_export_packet()
    """,
    """
    CREATE OR REPLACE FUNCTION append_accounting_outbox_history()
    RETURNS trigger AS $$
    BEGIN
        IF NEW.kind NOT IN ('food_accounting_group', 'store_accounting_group') THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'INSERT' THEN
            INSERT INTO accounting_outbox_attempts (
                company_id, packet_id, attempt_id, event, from_status, to_status,
                lease_until, ack_payload, component_result, error_code, error_detail
            ) VALUES (
                NEW.company_id, NEW.id, NEW.attempt_id, NEW.status, NULL, NEW.status,
                NEW.lease_until, NEW.ack_payload, NEW.component_result,
                NEW.error_code, NEW.error_detail
            );
        ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
            INSERT INTO accounting_outbox_attempts (
                company_id, packet_id, attempt_id, event, from_status, to_status,
                lease_until, ack_payload, component_result, error_code, error_detail
            ) VALUES (
                NEW.company_id, NEW.id, COALESCE(NEW.attempt_id, OLD.attempt_id),
                NEW.status, OLD.status, NEW.status, NEW.lease_until,
                NEW.ack_payload, NEW.component_result, NEW.error_code, NEW.error_detail
            );
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS accounting_outbox_history_trg ON export_packets",
    """
    CREATE TRIGGER accounting_outbox_history_trg
    AFTER INSERT OR UPDATE OF status ON export_packets
    FOR EACH ROW EXECUTE FUNCTION append_accounting_outbox_history()
    """,
    """
    CREATE OR REPLACE FUNCTION protect_accounting_outbox_attempt()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'accounting outbox history is append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS accounting_outbox_attempt_immutable_trg "
    "ON accounting_outbox_attempts",
    """
    CREATE TRIGGER accounting_outbox_attempt_immutable_trg
    BEFORE UPDATE OR DELETE ON accounting_outbox_attempts
    FOR EACH ROW EXECUTE FUNCTION protect_accounting_outbox_attempt()
    """,
)


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
        # v2.x: PIN станции для офлайн-входа на рабочем месте АЗС (edge-агент).
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS station_pin_hash VARCHAR(255)"
            )
        )
        # v0.8: реквизиты входящего документа (ТТН №+дата) и ВидОперации
        # для сверки ТТН-файл ↔ ПТУ и интерпретации проводок ОРП.
        # + period_status и discrepancy_* (см. docs/sverka-spec.md §7a):
        # обязательная отметка «закрытый период» и расхождений (включая копеечные).
        for stmt in (
            # Штатная структура: подразделение в членстве (org_departments создаёт
            # create_all; имя НЕ departments — коллизия с одноимённой таблицей
            # Поддержки в public уводила REFERENCES в чужую схему без прав).
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES org_departments(id) ON DELETE SET NULL",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS external_number VARCHAR(200)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS external_date VARCHAR(20)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS operation_type VARCHAR(100)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS period_status VARCHAR(10) NOT NULL DEFAULT 'open'",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_summary VARCHAR(500)",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS discrepancy_details JSONB",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_period_status ON accounting_docs(company_id, period_status)",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_discrepancy_status ON accounting_docs(company_id, discrepancy_status)",
            # Документ ↔ нормализованный слой: контрагент и договор ССЫЛКАМИ, а не
            # текстом. Пока покупатель хранится строкой, «его документы», «его долг» и
            # «его договоры» — три списка, которые между собой не сходятся: одно юрлицо
            # приезжает то с кавычками, то без, а платёж вообще приходит без ИНН.
            # Заполняет идемпотентное сведение (services/books_links.py), не загрузка.
            # Назначение файла: приём данных или вложение переписки. Без него
            # вложения чата попадали в слой приёма L1.
            "ALTER TABLE source_files ADD COLUMN IF NOT EXISTS purpose "
            "VARCHAR(20) NOT NULL DEFAULT 'data'",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS counterparty_id UUID "
            "REFERENCES counterparties(id) ON DELETE SET NULL",
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS contract_id UUID "
            "REFERENCES contracts(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_counterparty "
            "ON accounting_docs(company_id, counterparty_id)",
            "CREATE INDEX IF NOT EXISTS idx_accdoc_contract "
            "ON accounting_docs(company_id, contract_id)",
            # Приём первички: пакет загрузки и его кандидаты (services/intake_docs.py).
            # Таблицы заводит create_all; здесь — индексы разбора, по которым экран
            # ищет свои строки, и они же нужны на уже развёрнутых стендах.
            "CREATE INDEX IF NOT EXISTS idx_intake_items_batch "
            "ON intake_items(company_id, batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_intake_items_fp "
            "ON intake_items(company_id, fingerprint)",
            # Почтовый коннектор (docs/MAIL.md). Таблицы заводит create_all, но
            # КОЛОНКИ в уже существующую таблицу он не добавляет — на стенде,
            # поднятом до этой правки, опрос падал на `password_enc does not exist`.
            #
            # Настройка ящика сотрудником: пароль в базе под шифром (ключ — в
            # окружении стека), режимы шифрования, имя и подпись отправителя,
            # интервал опроса.
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS password_enc TEXT",
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS smtp_security VARCHAR(10) "
            "NOT NULL DEFAULT 'starttls'",
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS imap_security VARCHAR(10) "
            "NOT NULL DEFAULT 'ssl'",
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS display_name VARCHAR(200)",
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS signature TEXT",
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS poll_interval_min INTEGER "
            "NOT NULL DEFAULT 15",
            # Когда почта реально приходила: `last_sync_at` — «когда пытались», он
            # обновляется и при неудачном заходе, и витрина показывала свежий обмен
            # у ящика с неверным паролем.
            "ALTER TABLE mail_accounts ADD COLUMN IF NOT EXISTS last_ok_at "
            "TIMESTAMP WITH TIME ZONE",
            # Оригинал письма: разбор — наша интерпретация, спор решается исходником.
            "ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS raw_eml BYTEA",
            # Куда правило доставляет письмо: комната чата и объект для заявки.
            "ALTER TABLE mail_rules ADD COLUMN IF NOT EXISTS set_room_id UUID "
            "REFERENCES chat_rooms(id) ON DELETE SET NULL",
            "ALTER TABLE mail_rules ADD COLUMN IF NOT EXISTS set_object_id VARCHAR(100)",
            # Куда письмо доехало по факту: комната, задача, заявка.
            "ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS routed_to VARCHAR(20)",
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
            # Бизнес-роли Магазина — массив назначений с областью. Отдельно от
            # одной platform-роли и object_scope, чтобы права нескольких ролей
            # складывались, а администратор АЗС не получал соседние станции.
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS business_grants JSONB "
            "NOT NULL DEFAULT '[]'::jsonb",
            # Основание допуска: договоры, по которым человек работает в пространстве.
            # Не права — справка «на каком основании он здесь» (docs/SPACE.md §4).
            "ALTER TABLE user_companies ADD COLUMN IF NOT EXISTS contract_ids JSONB",
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
            # Куда зовут: в одну организацию или в пространство целиком. В контейнере
            # на одну компанию разницы нет, но в пространстве с несколькими (своя
            # практика + обслуживаемые организации) это два разных приглашения, и
            # человек обязан видеть, какое принимает.
            "ALTER TABLE invitations ADD COLUMN IF NOT EXISTS scope VARCHAR(10) "
            "NOT NULL DEFAULT 'company'",
            # Реквизиты документа, за которыми не заводят колонку: время проведения,
            # автор, договор, комментарий. Нужны срезу компании из бухгалтерии.
            "ALTER TABLE accounting_docs ADD COLUMN IF NOT EXISTS doc_meta JSONB",
            # Проводка → первичный документ: корень измерений «контрагент»,
            # «организация», «номенклатура» и разворота оборотки до первички.
            "ALTER TABLE gl_entries ADD COLUMN IF NOT EXISTS doc_id UUID "
            "REFERENCES accounting_docs(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS idx_gl_entries_doc ON gl_entries(company_id, doc_id)",
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
            # Обогащение сессии картой (витрина АСУиМ): в сессии от карты есть
            # только UID, а разбор нужен по номеру, статусу и владельцу.
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS card_number VARCHAR(60)",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS card_status VARCHAR(40)",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS card_owner_ext_id VARCHAR(40)",
            "ALTER TABLE charge_sessions ADD COLUMN IF NOT EXISTS card_foreign BOOLEAN",
            "CREATE INDEX IF NOT EXISTS idx_charge_sessions_card ON charge_sessions(company_id, card_number)",
            "CREATE INDEX IF NOT EXISTS idx_charge_sessions_card_status ON charge_sessions(company_id, card_status)",
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

        # v2.12: аналитика продаж ГИГ по реализациям (раздел «Продажи» → Аналитика/
        # Коммерция). Индекс под когорты «новые карты» (MIN(dt) GROUP BY card по
        # всей истории) и реестр карт. Досев паттернов маппинга оплат: на
        # ТРАНЗАКЦИОННОМ грейне STS имена видов оплаты отличаются от сменного
        # sales-блока («Карта МПС» = банковские карты 64% реализаций, «КР» =
        # локальные топливные карты, тех.отпуски) — без досева 2/3 реализаций
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

        # v2.13 УДАЛЕНА (12.08.2026). Здесь на каждом старте контейнера имена
        # объектов ЭЗС переписывались именем из свежайшей сессии — без охраны
        # `nameSource='cpo_registry'` и без фильтра по компании. Правило приоритета
        # «реестр CPO старше выгрузки сессий» соблюдает refresh_location_names()
        # (stations_normalize.py), и она же вызывается из конвейера сессий, поэтому
        # страховка не нужна: рестарт откатывал имя к сессионному, следующая
        # загрузка справочника возвращала обратно, и каждый круг дописывал элемент
        # в nameHistory. Так «Кафе Хорт» ходило туда-сюда с «(на тестировании)».

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
            # v2.16 (12.08.2026): у объектов сети не было НИ ОДНОГО уникального
            # ключа — отсюда три карточки с кодом «123» и пары AC/DC, слипшиеся по
            # серийнику. Код и серийник уникальны в пределах компании; тестовые
            # карточки CPO из проверки исключены (они и так вне индексов резолва).
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_service_locations_code "
            "ON service_locations (company_id, code) WHERE is_test = false",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_service_locations_serial "
            "ON service_locations (company_id, lower(serial_number)) "
            "WHERE is_test = false AND serial_number IS NOT NULL AND serial_number <> ''",
        ):
            # Уникальный индекс на живых данных может не построиться (дубликаты
            # накопились до правила). Падение роняло бы ВЕСЬ блок миграций и старт
            # контейнера, поэтому каждый индекс — в SAVEPOINT: неудача пишется в
            # лог, стенд поднимается, дубли видны в «Качестве данных».
            # ВАЖНО: именно SAVEPOINT на текущем соединении. Отдельная транзакция
            # (`engine.begin()`) здесь встаёт намертво — внешняя транзакция миграций
            # держит блокировку service_locations, и старт зависает на «Waiting for
            # application startup» без единой строки в логе.
            try:
                async with conn.begin_nested():
                    await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception as exc:  # noqa: BLE001
                __import__("logging").getLogger(__name__).warning(
                    "Уникальный индекс не создан (в данных есть дубликаты): %s", exc)

        # v2.16: чат (chat_rooms/participants/messages/reactions/folders — через
        # metadata.create_all). Здесь — presence-колонка + поля фазы 2 (закреп,
        # вложения) на существующих таблицах.
        for stmt in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
            # Участник чата, который живёт в своей почте: сообщения комнаты уходят
            # ему письмом, ответ возвращается в ленту. Войти такой учёткой нельзя.
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS mail_only BOOLEAN NOT NULL DEFAULT FALSE",
            # Фото человека: в чате и в составе пространства лицо читается быстрее
            # буквы в кружке — особенно в смешанной группе со сторонними.
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(300)",
            # Закреплённый чат — личная настройка каждого участника, не свойство комнаты.
            "ALTER TABLE chat_participants ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ",
            # Опрос со свободным ответом: участник дописывает свой вариант.
            "ALTER TABLE chat_polls ADD COLUMN IF NOT EXISTS allow_custom BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS pinned_message_id UUID",
            # Сообщение, пришедшее письмом: источник, Message-ID (идемпотентность
            # повторной доставки) и ссылка на письмо в архиве Поддержки.
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS external_source VARCHAR(20)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS external_id TEXT",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS external_ref VARCHAR(64)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_msg_external "
            "ON chat_messages (room_id, external_id) WHERE external_id IS NOT NULL",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url TEXT",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_name VARCHAR(500)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_size INTEGER",
            # v2.42: каналы и контекст чатов пространства. Тип «channel» и роль «owner»
            # живут в существующих строковых полях — ALTER нужен только под привязку
            # комнаты к приложению.
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS scope_product VARCHAR(40)",
            "CREATE INDEX IF NOT EXISTS idx_chat_rooms_scope ON chat_rooms (company_id, scope_product)",
            # v2.47: аватар чата — картинка из файлов пространства вместо иконки по типу.
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(300)",
            # v2.48: «без звука» на чат и пересылка сообщений (волна 1 фич Telegram).
            "ALTER TABLE chat_participants ADD COLUMN IF NOT EXISTS muted_until TIMESTAMPTZ",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS forwarded_from VARCHAR(255)",
            # v2.49: привязка чата к объекту пространства («группа по станции»).
            # На существующих таблицах — без FK (модель объявляет его для новых стеков);
            # осиротевшую привязку роутер просто не резолвит в имя.
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS scope_object_id VARCHAR(40)",
            # v2.50: чат заявки (скрытая группа при заявке Поддержки).
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS scope_ticket_id UUID",
            "CREATE INDEX IF NOT EXISTS idx_chat_rooms_ticket ON chat_rooms (scope_ticket_id)",
            # v2.51: выдача вложения сверяется с участием в разговоре (а не только с
            # компанией) — обратный поиск «файл → его сообщения» идёт на КАЖДУЮ картинку
            # в ленте, галерея открывает их десятками. Частичный: у большинства
            # сообщений вложения нет.
            "CREATE INDEX IF NOT EXISTS idx_chat_msg_file_url "
            "ON chat_messages (file_url) WHERE file_url IS NOT NULL",
            # v2.51: текст сообщения в уведомлении — по выбору устройства.
            "ALTER TABLE chat_push_subscriptions ADD COLUMN IF NOT EXISTS "
            "show_preview BOOLEAN NOT NULL DEFAULT TRUE",
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

        # v2.29: вид работы у проекта. Место и работа на нём — одна сущность
        # (решение 28.07.2026), поэтому вид переехал на неё: без него модернизация
        # действующего объекта не отличалась от новой стройки и получала этап
        # «Подбор площадки», которого в ней нет. Существующие записи — стройки:
        # они и заводились подбором площадки.
        for stmt in (
            "ALTER TABLE ezs_sites ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'new_build'",
            # Преемники (модернизация, перенос, демонтаж) уже помечены в спутнике —
            # переносим вид оттуда, чтобы заведённые до миграции не потерялись.
            """
            UPDATE ezs_sites s SET kind = p.kind
              FROM ezs_projects p
             WHERE p.site_id = s.id AND p.kind <> 'new_build' AND s.kind = 'new_build'
            """,
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.30: единый справочник видов договоров и роли сторон.
        #
        # Вид договора хранился свободным текстом, и один вид писался по-разному:
        # «Сервисное обслуживание», «Сервис», «Техническое обслуживание ЭЗС» —
        # три написания, по которым считают охват и обязательства. Теперь код,
        # название и основание по ГК; исходный текст остаётся в contracts.type,
        # чтобы разбор можно было проверить и ничего не потерять.
        #
        # Роль контрагента намеренно не хранится в его карточке: один и тот же
        # бывает арендодателем по одному договору, поставщиком по другому и
        # покупателем по третьему. Роль — свойство участия в договоре.
        for stmt in (
            """
            CREATE TABLE IF NOT EXISTS contract_types (
              code        TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              gk_basis    TEXT,
              direction   TEXT,
              sort_order  INT NOT NULL DEFAULT 100,
              is_active   BOOLEAN NOT NULL DEFAULT true
            )
            """,
            """
            INSERT INTO contract_types (code, label, gk_basis, direction, sort_order) VALUES
              ('rent',             'Аренда',                    'гл. 34 ГК РФ',     'in',  10),
              ('energy_supply',    'Энергоснабжение',           '§ 6 гл. 30 ГК РФ', 'in',  20),
              ('works',            'Подряд и монтаж',           'гл. 37 ГК РФ',     'in',  30),
              ('supply',           'Поставка оборудования',     '§ 3 гл. 30 ГК РФ', 'in',  40),
              ('maintenance',      'Техническое обслуживание',  'гл. 39 ГК РФ',     'in',  50),
              ('services',         'Возмездное оказание услуг', 'гл. 39 ГК РФ',     'any', 60),
              ('contact_center',   'Услуги контакт-центра',     'гл. 39 ГК РФ',     'in',  70),
              ('agency',           'Агентский договор',         'гл. 52 ГК РФ',     'any', 80),
              ('sale',             'Купля-продажа',             'гл. 30 ГК РФ',     'any', 90),
              ('charging_service', 'Зарядка электромобилей',    'гл. 39 ГК РФ',     'out', 100),
              ('other',            'Иное',                       NULL,              'any', 200)
            ON CONFLICT (code) DO UPDATE
              SET label = EXCLUDED.label, gk_basis = EXCLUDED.gk_basis,
                  direction = EXCLUDED.direction, sort_order = EXCLUDED.sort_order
            """,
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS type_code TEXT REFERENCES contract_types(code)",
            "CREATE INDEX IF NOT EXISTS idx_contracts_type_code ON contracts (company_id, type_code)",
            # Разбор накопленного текста. Список закрытый: что не опознано, остаётся
            # без кода и видно запросом, а не растворяется в «прочем».
            """
            UPDATE contracts SET type_code = CASE
                WHEN type ILIKE '%аренд%'                                      THEN 'rent'
                WHEN type ILIKE '%энергоснабж%' OR type ILIKE '%электроэнерг%' THEN 'energy_supply'
                WHEN type ILIKE '%монтаж%' OR type ILIKE '%подряд%'            THEN 'works'
                WHEN type ILIKE '%поставка%'                                   THEN 'supply'
                WHEN type ILIKE '%сервис%' OR type ILIKE '%обслуживан%'        THEN 'maintenance'
                WHEN type ILIKE '%зарядк%'                                     THEN 'charging_service'
                WHEN type ILIKE '%эквайринг%' OR type ILIKE '%ОФД%'            THEN 'services'
                ELSE NULL
              END
            WHERE type_code IS NULL AND type IS NOT NULL
            """,
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # v2.31: реестр «Операций» ГИГ вровень с «Монитором» — поля реализации, которые
        # STS отдаёт с первого дня, а ингест не сохранял: номер чека (по нему ищут
        # конкретную заправку), заказ клиента до отпуска («залей на 1000 ₽» —
        # расхождение с фактом видно в карточке), масса, статус и нормализованный
        # вид оплаты (по нему группируются KPI-карточки).
        for stmt in (
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS receipt INTEGER",
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS payment_method VARCHAR(120)",
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS mass NUMERIC(14,3)",
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS order_qty NUMERIC(14,3)",
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS order_cost NUMERIC(16,2)",
            "ALTER TABLE fuel_transactions ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'completed'",
            "CREATE INDEX IF NOT EXISTS idx_ftx_company_payment_dt "
            "ON fuel_transactions (company_id, payment_method, dt)",
            "CREATE INDEX IF NOT EXISTS idx_ftx_company_receipt "
            "ON fuel_transactions (company_id, receipt) WHERE receipt IS NOT NULL",
        ):
            await conn.execute(__import__("sqlalchemy").text(stmt))

        # Бэкфилл payment_method по уже загруженным реализациям: идём по РАЗЛИЧНЫМ сырым
        # именам (их десятки на сотни тысяч строк) и через ту же функцию, что и
        # ингест — SQL-двойник этой логики со временем разошёлся бы с ней.
        # Чек, заказ и массу бэкфиллом не взять: они приезжают только повторной
        # загрузкой периода из STS (кнопка «Загрузить реализации» в разделе).
        from app.services.payment_normalize import normalize_payment_method
        _sa = __import__("sqlalchemy")
        for raw in (await conn.execute(_sa.text(
            "SELECT DISTINCT pay_type_name FROM fuel_transactions WHERE payment_method IS NULL"
        ))).scalars().all():
            await conn.execute(
                _sa.text("UPDATE fuel_transactions SET payment_method = :norm "
                         "WHERE payment_method IS NULL AND pay_type_name IS NOT DISTINCT FROM :raw"),
                {"norm": normalize_payment_method(raw), "raw": raw},
            )

        # -------------------------------------------------------------------
        # v2.32: «Эксплуатация» — денежный контур площадок (волна 0).
        # -------------------------------------------------------------------
        # Таблицы ops_* создаёт metadata.create_all. Здесь — сид справочника
        # статей (закрытый список, правится вместе с кодом, как contract_types),
        # показания приборов учёта в готовую station_energy_periods и два
        # разовых бэкфилла, которые поднимают контур на реальных данных.

        # Дефолт под сырой INSERT ниже: колонка объявлена NOT NULL с python-default,
        # а сеялка идёт SQL-ом и значения не передаёт — на базе, где таблица создана
        # без server_default, старт падал на NotNullViolationError.
        await conn.execute(_sa.text(
            "ALTER TABLE ops_cost_items ALTER COLUMN is_active SET DEFAULT true"))

        # Статьи затрат. Активны те, под которые есть условия; включение новой
        # статьи — строка здесь плюс условия в реестре, кода писать не нужно.
        await conn.execute(_sa.text("""
            INSERT INTO ops_cost_items
              (code, label, contract_type_code, settlement_role, measure,
               default_expected_docs, default_estimate_basis, bp_account, sort_order) VALUES
              ('rent',            'Аренда площадки',       'rent',          'rent',    'fixed',
               '{act,invoice}',        'contract',    '20',  10),
              ('energy',          'Электроэнергия',        'energy_supply', 'energy',  'metered',
               '{upd,invoice,report}', 'prev_period', '20',  20),
              ('maintenance',     'Обслуживание и ТО',     'maintenance',   'service', 'fixed',
               '{act,invoice}',        'contract',    '20',  30),
              ('tech_connection', 'Технологическое присоединение', 'services', NULL,   'fixed',
               '{act,invoice}',        'contract',    '08',  40),
              ('comms',           'Связь и передача данных', 'services',    NULL,      'fixed',
               '{act,invoice}',        'prev_period', '26',  50),
              ('cleaning',        'Уборка и содержание',   'services',      NULL,      'fixed',
               '{act,invoice}',        'contract',    '20',  60),
              ('other',           'Прочие расходы',         NULL,           NULL,      'fixed',
               '{act}',                'average',     '26',  90)
            ON CONFLICT (code) DO UPDATE
              SET label = EXCLUDED.label,
                  contract_type_code = EXCLUDED.contract_type_code,
                  settlement_role = EXCLUDED.settlement_role,
                  measure = EXCLUDED.measure,
                  default_expected_docs = EXCLUDED.default_expected_docs,
                  default_estimate_basis = EXCLUDED.default_estimate_basis,
                  bp_account = EXCLUDED.bp_account,
                  sort_order = EXCLUDED.sort_order
        """))

        # Показания ПУ и коэффициент трансформации: объём = (curr − prev) × КТ.
        # create_all колонки в готовую таблицу не добавляет.
        for stmt in (
            "ALTER TABLE station_energy_periods ADD COLUMN IF NOT EXISTS meter_prev DOUBLE PRECISION",
            "ALTER TABLE station_energy_periods ADD COLUMN IF NOT EXISTS meter_curr DOUBLE PRECISION",
            "ALTER TABLE station_energy_periods ADD COLUMN IF NOT EXISTS ktrans DOUBLE PRECISION",
            "ALTER TABLE station_energy_periods ADD COLUMN IF NOT EXISTS meter_id UUID "
            "REFERENCES ops_meters(id) ON DELETE SET NULL",
        ):
            await conn.execute(_sa.text(stmt))

        # ── Бэкфилл 1: охват договоров по объектам ──
        # У 876 договоров scope_type='locations', а contract_locations заполнена
        # у 26: привязку ингест реестра проставил в station_contract_settlements,
        # но в ось «договор ↔ точка» она не доехала. Без неё ожидание по договору
        # не на что разворачивать.
        #
        # Разовый: маркер в note. Иначе привязка, снятая человеком вручную как
        # ошибочная, возвращалась бы при каждом рестарте.
        if not (await conn.execute(_sa.text(
            "SELECT 1 FROM contract_locations WHERE note = 'backfill:settlements' LIMIT 1"
        ))).first():
            await conn.execute(_sa.text("""
                INSERT INTO contract_locations (id, company_id, contract_id, location_id, note)
                SELECT gen_random_uuid(), s.company_id, s.contract_id, s.location_id,
                       'backfill:settlements'
                  FROM station_contract_settlements s
                  JOIN contracts c ON c.id = s.contract_id
                 WHERE s.contract_id IS NOT NULL
                   -- Фильтр обязателен: общекомпанийный договор с объектной
                   -- привязкой посчитался бы дважды — и по объектам, и как общий.
                   AND c.scope_type = 'locations'
                ON CONFLICT DO NOTHING
            """))

        # ── Бэкфилл 2: условия обязательств из реестра контрагента ──
        # 1229 строк реестра (аренда 421, энергия 398) уже несут сумму, НДС и
        # горизонт договора — это готовые условия, из которых разворачивается
        # ожидание месяца. Дальше условия живут своей жизнью: реестр отвечает за
        # дисциплину ОПЛАТЫ, условия — за дисциплину ДОКУМЕНТОВ, и повторная
        # загрузка файла их не трогает.
        if not (await conn.execute(_sa.text(
            "SELECT 1 FROM ops_contract_terms WHERE source = 'backfill:settlements' LIMIT 1"
        ))).first():
            await conn.execute(_sa.text("""
                INSERT INTO ops_contract_terms
                  (id, company_id, contract_id, cost_item, scope_type, location_id,
                   periodicity, amount_gross, amount_net, vat_pct,
                   variable_kind, tariff_rub, valid_from, valid_to, source, extra)
                SELECT gen_random_uuid(), s.company_id, s.contract_id,
                       CASE s.role WHEN 'rent' THEN 'rent' ELSE 'energy' END,
                       'location', s.location_id,
                       'monthly',
                       s.amount_gross, s.amount_net, s.vat_pct,
                       CASE WHEN s.role = 'energy' THEN 'metered_kwh' END,
                       NULLIF(s.extra->>'avgTariff', '')::NUMERIC,
                       -- Горизонт версии. Дата начала неизвестна у большинства
                       -- строк — берём заведомо ранний якорь, чтобы условие
                       -- действовало на всю доступную историю.
                       COALESCE(NULLIF(LEFT(s.contract_start, 10), ''), '2019-01-01'),
                       NULLIF(LEFT(s.contract_end, 10), ''),
                       'backfill:settlements',
                       jsonb_build_object('paymentStatus', s.payment_status,
                                          'basis', s.basis, 'comment', s.comment)
                  FROM station_contract_settlements s
                 WHERE s.contract_id IS NOT NULL
                   AND s.role IN ('rent', 'energy')
                ON CONFLICT DO NOTHING
            """))

        # v2.33: отдельная аналитика изменений проектов.
        # Старый `text='owner_user_id, stage'` не содержит прежних значений и не
        # позволяет честно показать «было → стало». Новые события хранят снимок
        # изменённых полей; старые остаются как неполная история.
        for stmt in (
            "ALTER TABLE ezs_site_events ADD COLUMN IF NOT EXISTS changes JSONB",
            "ALTER TABLE ezs_site_events ADD COLUMN IF NOT EXISTS source "
            "VARCHAR(16) NOT NULL DEFAULT 'user'",
            """
            UPDATE ezs_site_events
               SET source = 'import'
             WHERE source = 'user'
               AND (kind = 'import' OR text LIKE 'Импорт:%')
            """,
            "CREATE INDEX IF NOT EXISTS ix_ezs_site_event_company_created "
            "ON ezs_site_events (company_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_ezs_site_event_changes_gin "
            "ON ezs_site_events USING GIN (changes) WHERE changes IS NOT NULL",
        ):
            await conn.execute(_sa.text(stmt))

        # В3 (docs/CONNECT.md): трасса «какой канал породил запись» — channel_id
        # у всех целевых таблиц загрузок. NULL = ручная загрузка / старые данные.
        for tbl in ("fuel_shifts", "fuel_receipts", "online_orders", "data_entries"):
            await conn.execute(_sa.text(
                f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS channel_id UUID "
                f"REFERENCES channels(id) ON DELETE SET NULL"))

        # v2.34: единица выхода нужна для вложенных ТТК: полуфабрикат с
        # выходом 500 г нельзя использовать строкой в миллилитрах.
        await conn.execute(_sa.text(
            "ALTER TABLE store_recipe_versions ADD COLUMN IF NOT EXISTS "
            "output_unit VARCHAR(20) NOT NULL DEFAULT 'шт'"))
        await conn.execute(_sa.text(
            "ALTER TABLE store_recipe_versions ADD COLUMN IF NOT EXISTS "
            "source VARCHAR(20) NOT NULL DEFAULT 'center'"))
        await conn.execute(_sa.text(
            "ALTER TABLE store_recipe_versions ADD COLUMN IF NOT EXISTS "
            "source_station_id INTEGER"))
        await conn.execute(_sa.text(
            "ALTER TABLE store_recipe_versions ADD COLUMN IF NOT EXISTS "
            "change_note VARCHAR(500)"))
        await conn.execute(_sa.text(
            "ALTER TABLE store_recipe_versions ADD COLUMN IF NOT EXISTS "
            "source_bundle_id VARCHAR(100)"))

        # v2.35: UUID пакета детерминирован номером станции и сменой. Одинаковые
        # номера станций в разных компаниях не должны блокировать друг друга.
        await conn.execute(_sa.text(
            "ALTER TABLE edge_packets DROP CONSTRAINT IF EXISTS "
            "edge_packets_packet_uuid_key"))
        await conn.execute(_sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_edge_packets_company_packet "
            "ON edge_packets (company_id, packet_uuid)"))

        # v2.36: две схемы доставки и два маршрута подписания приёмки.
        for stmt in (
            "ALTER TABLE store_receipts ALTER COLUMN station_id DROP NOT NULL",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS delivery_scheme "
            "VARCHAR(30) NOT NULL DEFAULT 'supplier_to_station'",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS receiving_warehouse VARCHAR(200)",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS signing_mode "
            "VARCHAR(30) NOT NULL DEFAULT 'office_director'",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS signer_name VARCHAR(200)",
            # Кто принял товар на станции. Прежние документы остаются без автора:
            # задним числом его взять неоткуда, пустое честнее подставленного.
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS author VARCHAR(200)",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS mchd_guid VARCHAR(100)",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS mchd_registry VARCHAR(200)",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS mchd_valid_until DATE",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS signature_status "
            "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS signature_ref VARCHAR(200)",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ",
            "ALTER TABLE store_receipts ADD COLUMN IF NOT EXISTS distribution "
            "JSONB NOT NULL DEFAULT '[]'::jsonb",
        ):
            await conn.execute(_sa.text(stmt))

        # v2.38: единый документ приёмки, идемпотентный downlink и неизменяемые
        # складские проводки центрального склада. Для старой БД одного изменения
        # ORM недостаточно: create_all не добавляет колонки в готовую таблицу.
        for stmt in STORE_RECEIPT_MIGRATION_DDL:
            await conn.execute(_sa.text(stmt))

        # v2.39: fail-closed policy/manifest/shadow для бухгалтерского egress
        # сопутки и общепита. Триггер policy дублирует сервисную проверку и не
        # позволяет создать неоднозначный transport producer прямым SQL.
        for stmt in ACCOUNTING_EGRESS_MIGRATION_DDL:
            await conn.execute(_sa.text(stmt))

        # v2.40: канонические ревизии L2 и ревизионный accounting-only outbox.
        # Legacy/fuel idem_key сохраняет прежнюю семантику отдельным predicate.
        for stmt in ACCOUNTING_REVISION_MIGRATION_DDL:
            await conn.execute(_sa.text(stmt))

        # v2.42: кто завёл черновик на станции.
        #
        # У цены и заявки на правку канона автор обязателен — «представьтесь:
        # центр должен видеть, кто заявил». У карточки и контрагента его не было
        # вовсе: в очереди признания видно, ЧТО предлагают и с какой АЗС, но не
        # КТО, а решение центра переклеивает учёт станции.
        await conn.execute(_sa.text("""
            DO $$ BEGIN
                IF to_regclass('edge.item_draft') IS NOT NULL THEN
                    ALTER TABLE edge.item_draft
                        ADD COLUMN IF NOT EXISTS author VARCHAR(120) NOT NULL DEFAULT '';
                END IF;
                IF to_regclass('edge.partner_draft') IS NOT NULL THEN
                    ALTER TABLE edge.partner_draft
                        ADD COLUMN IF NOT EXISTS author VARCHAR(120) NOT NULL DEFAULT '';
                END IF;
            END $$
        """))

        # v2.41: у перевыгрузки появился исход.
        #
        # Станция вправе прислать пакет заново с исправленным содержимым. Такой
        # пакет откладывается ревизией needs_review — и лежал там вечно: читать
        # его было некому, применить нечем, а обещание «исправление станции не
        # потеряется» держалось на одной записи в таблицу.
        #
        # Решение — отдельный факт, а не правка ревизии: raw-ревизии append-only
        # (триггер protect_edge_packet_revision запрещает UPDATE и DELETE), и это
        # правильно — доказательство доставки не переписывают. Прежняя версия
        # пакета при замене сохраняется обычной ревизией, то есть тем же
        # доказательством, и остаётся обратный ход.
        await conn.execute(_sa.text("""
            CREATE TABLE IF NOT EXISTS edge_packet_revision_decisions (
                id           UUID PRIMARY KEY,
                company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                revision_id  UUID NOT NULL REFERENCES edge_packet_revisions(id),
                decision     VARCHAR(10) NOT NULL,
                decided_by   VARCHAR(200) NOT NULL DEFAULT '',
                decided_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                note         TEXT NOT NULL DEFAULT '',
                CONSTRAINT ck_edge_revision_decision
                    CHECK (decision IN ('applied', 'rejected')),
                CONSTRAINT uq_edge_revision_decision UNIQUE (revision_id)
            )
        """))
        # Ограничение статусов вернули к исходному: применённость ревизии
        # хранится решением, а не её собственным полем.
        await conn.execute(_sa.text(
            "ALTER TABLE edge_packet_revisions "
            "DROP CONSTRAINT IF EXISTS ck_edge_packet_revision_status"))
        await conn.execute(_sa.text(
            "ALTER TABLE edge_packet_revisions ADD CONSTRAINT "
            "ck_edge_packet_revision_status CHECK (status IN "
            "('received','needs_review'))"))

        # v2.37: станция заявляет об ошибке в сетевой карточке.
        #
        # Канон ведёт центр, но ошибку в карточке первым видит тот, кто стоит у
        # полки: не та ставка, кривое название, штрихкод, который не сканируется.
        # Раньше у станции было два выхода — звонить или завести дубль; на 208
        # так набралось 95 групп дублей. Теперь у неё есть право заявить, а
        # решение остаётся за центром.
        # Схему `edge` заводит инициализатор базы пространства (support-db-run.sh) — у
        # роли приложения нет права CREATE на базе, и «CREATE SCHEMA IF NOT EXISTS»
        # отсюда падает с permission denied ДАЖЕ когда схема уже есть.
        await conn.execute(_sa.text("""
            CREATE TABLE IF NOT EXISTS edge.nsi_proposal (
                id          BIGSERIAL PRIMARY KEY,
                company_id  UUID NOT NULL,
                station_id  INTEGER NOT NULL,
                source_uuid VARCHAR(64) NOT NULL,
                item_uuid   VARCHAR(64) NOT NULL,
                field       VARCHAR(30) NOT NULL,
                current     TEXT NOT NULL DEFAULT '',
                proposed    TEXT NOT NULL,
                author      VARCHAR(120) NOT NULL DEFAULT '',
                comment     TEXT NOT NULL DEFAULT '',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at TIMESTAMPTZ,
                rejected    BOOLEAN NOT NULL DEFAULT false,
                note        TEXT,
                CONSTRAINT uq_nsi_proposal UNIQUE (company_id, station_id, source_uuid)
            )
        """))

        # Политика Магазина v1: цены всех карточек находятся в ведении АЗС.
        # Колонка остаётся — позже она снова станет различаться по категории
        # или карточке, когда будет включён сетевой контроль ценообразования.
        await conn.execute(_sa.text("""
            DO $$ BEGIN
                IF to_regclass('edge.item') IS NOT NULL THEN
                    UPDATE edge.item SET price_owner = 'station'
                    WHERE coalesce(price_owner, '') <> 'station';
                END IF;
            END $$
        """))

        # v2.38: задание центра можно отменить, не выдавая его за применённое.
        #
        # Агент забирает всё неподтверждённое, поэтому единственным способом
        # убрать ошибочное задание из очереди было проставить ему acked_at —
        # то есть соврать, что станция его применила. Отмена — отдельное
        # событие со своим временем и автором.
        for stmt in (
            "ALTER TABLE edge_downlink ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ",
            "ALTER TABLE edge_downlink ADD COLUMN IF NOT EXISTS cancelled_by UUID",
        ):
            await conn.execute(_sa.text(stmt))

        # Фактический трафик станции: size_bytes хранит JSON после распаковки,
        # поэтому выдавать его за объём LTE-канала нельзя.
        await conn.execute(_sa.text(
            "ALTER TABLE edge_packets ADD COLUMN IF NOT EXISTS wire_size_bytes INTEGER"))

        # v2.39: у документа станции появились сквозной номер центра и статус.
        #
        # Номер присваивает касса, и у двух АЗС он совпадает; в претензии
        # поставщику нужен номер, который в сети один. Статус отвечает, что с
        # документом сделали здесь: принят, проверен, спорный, закрыт.
        for stmt in (
            "ALTER TABLE store_cheques ADD COLUMN IF NOT EXISTS version "
            "INTEGER NOT NULL DEFAULT 1",
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_store_cheque_version') THEN "
            "ALTER TABLE store_cheques ADD CONSTRAINT ck_store_cheque_version "
            "CHECK (version > 0) NOT VALID; END IF; END $$",
            "ALTER TABLE store_document_projections ADD COLUMN IF NOT EXISTS "
            "projection_source VARCHAR(20)",
            "ALTER TABLE store_document_projections ADD COLUMN IF NOT EXISTS "
            "accounting_group_id UUID",
            "ALTER TABLE store_document_projections ADD COLUMN IF NOT EXISTS "
            "document_role VARCHAR(30)",
            "ALTER TABLE store_document_projections ADD COLUMN IF NOT EXISTS "
            "source_document_id UUID",
            "ALTER TABLE store_document_projections ALTER COLUMN vat_amount DROP NOT NULL",
            "UPDATE store_document_projections SET document_role = CASE "
            "WHEN source_kind IN ('cheque','store_shift') THEN 'fiscal' "
            "WHEN source_kind IN ('accounting_doc','accounting_packet',"
            "'onec_inventory','onec_movement') THEN 'accounting_derived' "
            "WHEN source_kind IN ('receipt','canonical_entry') THEN 'primary_evidence' "
            "ELSE 'operational' END WHERE document_role IS NULL",
            "ALTER TABLE store_document_projections ALTER COLUMN document_role SET NOT NULL",
            "CREATE INDEX IF NOT EXISTS ix_store_document_projection_accounting_group "
            "ON store_document_projections (company_id, accounting_group_id)",
            "CREATE INDEX IF NOT EXISTS ix_store_document_projection_source_document "
            "ON store_document_projections (company_id, projection_source, source_document_id)",
            "UPDATE store_document_projections SET projection_source = CASE "
            "WHEN source_kind IN ('receipt') THEN 'store' "
            "WHEN source_kind IN ('edge_document') THEN 'edge' "
            "WHEN source_kind IN ('cheque','store_shift') THEN 'cash' "
            "WHEN source_kind IN ('onec_inventory','onec_movement') THEN 'onec_legacy' "
            "WHEN source_kind = 'accounting_doc' THEN 'bp' "
            "WHEN source_kind = 'canonical_entry' AND "
            "header->>'fact_origin' IN ('edge','store','onec_legacy','edo','cash','bp') "
            "THEN header->>'fact_origin' ELSE 'store' END "
            "WHERE projection_source IS NULL",
            "ALTER TABLE store_document_projections ALTER COLUMN projection_source SET NOT NULL",
            "ALTER TABLE store_document_projections DROP CONSTRAINT IF EXISTS "
            "uq_store_document_projection_source",
            "ALTER TABLE store_document_projections ADD CONSTRAINT "
            "uq_store_document_projection_source UNIQUE "
            "(company_id, projection_source, source_kind, source_record_id)",
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_store_document_projection_source') THEN "
            "ALTER TABLE store_document_projections ADD CONSTRAINT "
            "ck_store_document_projection_source CHECK "
            "(projection_source IN ('edge','store','onec_legacy','edo','cash','bp')) "
            "NOT VALID; END IF; END $$",
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_store_document_projection_role') THEN "
            "ALTER TABLE store_document_projections ADD CONSTRAINT "
            "ck_store_document_projection_role CHECK "
            "(document_role IN ('primary_evidence','operational','fiscal',"
            "'accounting_derived')) NOT VALID; END IF; END $$",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS reg_number VARCHAR(40)",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS status "
            "VARCHAR(20) NOT NULL DEFAULT 'принят'",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS record_id UUID",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS document_id UUID",
            "ALTER TABLE store_doc_meta ADD COLUMN IF NOT EXISTS revision INTEGER",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_doc_meta_reg "
            "ON store_doc_meta (reg_number) WHERE reg_number IS NOT NULL",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS record_id UUID",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS document_id UUID",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS role VARCHAR(30)",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS sha256 CHAR(64)",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS revision INTEGER",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS author_id UUID "
            "REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS tombstoned_at TIMESTAMPTZ",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS tombstoned_by UUID "
            "REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE store_doc_files ADD COLUMN IF NOT EXISTS tombstone_reason VARCHAR(300)",
            "UPDATE store_doc_files SET role = kind WHERE role IS NULL",
            "UPDATE store_doc_files SET author_id = uploaded_by WHERE author_id IS NULL",
            "UPDATE store_doc_files SET revision = 1 WHERE revision IS NULL",
            "CREATE INDEX IF NOT EXISTS ix_store_doc_files_record "
            "ON store_doc_files (company_id, record_id, tombstoned_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_doc_file_revision "
            "ON store_doc_files (record_id, revision, role, sha256) "
            "WHERE record_id IS NOT NULL AND revision IS NOT NULL "
            "AND role IS NOT NULL AND sha256 IS NOT NULL",
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_store_doc_file_sha256') THEN "
            "ALTER TABLE store_doc_files ADD CONSTRAINT ck_store_doc_file_sha256 "
            "CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$') NOT VALID; "
            "END IF; END $$",
        ):
            await conn.execute(_sa.text(stmt))

        # v2.42: телефоны в карточке человека — как с ним связаться помимо чата.
        for stmt in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_mobile VARCHAR(40)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_office VARCHAR(40)",
        ):
            await conn.execute(_sa.text(stmt))

        # v2.41: новичок в группе может прийти «с чистого листа».
        #
        # Кто добавляет, тот и решает, видно ли новому участнику прошлое группы.
        # По умолчанию видно (NULL) — в рабочую группу зовут ради контекста;
        # время в поле означает «читает только то, что после его прихода».
        await conn.execute(_sa.text(
            "ALTER TABLE chat_participants ADD COLUMN IF NOT EXISTS history_from TIMESTAMPTZ"))

        # v2.40: натуральный ключ документа L2 — DB-страховка от задвоения.
        #
        # Агент шлёт смену несколькими пакетами подряд; их приём идёт в
        # параллельных транзакциях, и поиск «а нет ли уже такой записи» не видит
        # чужую незакоммиченную. Три пакета смены 08.06 дали по три копии каждой
        # ТТК. Индекс превращает тихий дубль в конфликт, который ретрай агента
        # залечивает сам. Частичный: у топливной линии (source='api') ключа нет.
        for stmt in (
            # осиротевшие копии: оставляем самую свежую запись ключа.
            # Ранжируем по (updated_at, id) с NULLS LAST — у части строк времени
            # нет, а обычное сравнение с NULL не удалило бы ничего и индекс не встал.
            "DELETE FROM data_entries WHERE id IN ("
            "  SELECT id FROM (SELECT id, row_number() OVER ("
            "      PARTITION BY company_id, source, source_id"
            "      ORDER BY updated_at DESC NULLS LAST, id DESC) rn"
            "    FROM data_entries WHERE COALESCE(source_id, '') <> '') t"
            "  WHERE rn > 1)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_entries_source_key "
            "ON data_entries (company_id, source, source_id) "
            "WHERE COALESCE(source_id, '') <> ''",
        ):
            await conn.execute(_sa.text(stmt))

        # «Пульс»: карточку можно не только принять на сегодня, но и отложить —
        # «вернуться через три дня». Без срока «Принято» означало «я видел», и
        # решение руководителя нигде не оставляло следа до самого провала.
        for stmt in (
            "ALTER TABLE pulse_acks ADD COLUMN IF NOT EXISTS snooze_until DATE",
            "ALTER TABLE pulse_acks ADD COLUMN IF NOT EXISTS note TEXT",
        ):
            await conn.execute(_sa.text(stmt))

        # «Задачи»: внешние участники (docs/TASKS.md §9). `create_all` заводит
        # только НОВЫЕ таблицы — колонку в существующую он не добавит, поэтому
        # обе идут сюда, иначе на живом стенде INSERT падает «column does not exist».
        for stmt in (
            # У кого мяч: ждём себя или внешнюю сторону.
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS waiting_for VARCHAR(20)",
            # Имя автора без учётки: письмо мог прислать человек, которого в
            # пространстве нет вовсе.
            "ALTER TABLE task_events ADD COLUMN IF NOT EXISTS actor_name VARCHAR(200)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_waiting ON tasks(company_id, waiting_for)",
            # Регламент: время реакции и кому эскалировать — свойство типа.
            "ALTER TABLE task_types ADD COLUMN IF NOT EXISTS reaction_hours INTEGER",
            "ALTER TABLE task_types ADD COLUMN IF NOT EXISTS escalate_to_id UUID "
            "REFERENCES users(id) ON DELETE SET NULL",
            # Отклик исполнителя и отметка о последнем напоминании.
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reacted_at TIMESTAMPTZ",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ",
            # Учёт времени: план в задаче, факт — в task_work_items.
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS estimate_minutes INTEGER",
            # Видимость: company (по умолчанию) или private — только причастные.
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) "
            "NOT NULL DEFAULT 'company'",
            # Закреплённая реплика ленты: главное решение наверх.
            "ALTER TABLE task_events ADD COLUMN IF NOT EXISTS pinned BOOLEAN "
            "NOT NULL DEFAULT false",
            # Чат задачи — скрытая группа обсуждения, как у заявки.
            "ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS scope_task_id UUID "
            "REFERENCES tasks(id) ON DELETE CASCADE",
            "CREATE INDEX IF NOT EXISTS idx_chat_rooms_task ON chat_rooms (scope_task_id)",
            # Проекты ЭЗС: серийный номер станции вносит ОКС по ходу СМР — раньше
            # постановки на учёт, когда единицы склада ещё нет.
            "ALTER TABLE ezs_site_equipment ADD COLUMN IF NOT EXISTS serial_number VARCHAR(120)",
            # Сведение аналитики оборотов: виды субконто счёта и ссылки на карточки.
            # Пока субконто было строкой, «Разрывов связей» в модели данных считались
            # тысячами (у НПК 17 398 из 18 045), а взаиморасчёты по оборотам нельзя
            # было открыть карточкой контрагента.
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS title VARCHAR(300)",
            # Договор был единственным местом ядра, где контрагент и юрлицо хранились
            # СТРОКОЙ без внешнего ключа: целостность не проверялась, а каждый запрос
            # писал `::text`. Значения — валидные UUID (проверено на трёх компаниях),
            # поэтому перевод безопасен; ошибку приведения глотаем, чтобы старт не
            # падал на базе, где кто-то успел записать не-UUID.
            "DO $$ BEGIN"
            " ALTER TABLE contracts ALTER COLUMN counterparty_id TYPE uuid"
            "   USING counterparty_id::uuid;"
            " EXCEPTION WHEN others THEN NULL; END $$",
            "DO $$ BEGIN"
            " ALTER TABLE contracts ALTER COLUMN organization_id TYPE uuid"
            "   USING organization_id::uuid;"
            " EXCEPTION WHEN others THEN NULL; END $$",
            "CREATE INDEX IF NOT EXISTS idx_contracts_company_cp"
            " ON contracts (company_id, counterparty_id)",
            # Отбор по компании — первый в КАЖДОМ запросе слоя. Без индекса это
            # полный скан: у номенклатуры пять тысяч строк на три компании.
            "CREATE INDEX IF NOT EXISTS idx_counterparties_company ON counterparties (company_id)",
            "CREATE INDEX IF NOT EXISTS idx_nomenclature_company ON nomenclature (company_id)",
            "CREATE INDEX IF NOT EXISTS idx_periods_company ON periods (company_id)",
            "CREATE INDEX IF NOT EXISTS idx_organizations_company ON organizations (company_id)",
            "CREATE INDEX IF NOT EXISTS idx_refsnap_company ON reference_snapshots (company_id)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS valid_until VARCHAR(20)",
            "ALTER TABLE gl_accounts ADD COLUMN IF NOT EXISTS subconto JSONB",
            "ALTER TABLE gl_turnovers ADD COLUMN IF NOT EXISTS dt_counterparty_id UUID",
            "ALTER TABLE gl_turnovers ADD COLUMN IF NOT EXISTS kt_counterparty_id UUID",
            "ALTER TABLE gl_turnovers ADD COLUMN IF NOT EXISTS dt_contract_id UUID",
            "ALTER TABLE gl_turnovers ADD COLUMN IF NOT EXISTS kt_contract_id UUID",
            "ALTER TABLE gl_turnovers ADD COLUMN IF NOT EXISTS sub_links JSONB",
            "CREATE INDEX IF NOT EXISTS idx_gl_turnovers_dt_cp "
            "ON gl_turnovers (company_id, dt_counterparty_id)",
            "CREATE INDEX IF NOT EXISTS idx_gl_turnovers_kt_cp "
            "ON gl_turnovers (company_id, kt_counterparty_id)",
            # «Дело», вторая волна: визы и номенклатура дел. Таблицы create_all
            # заводит сам, а колонки в уже существующие — нет, и на живом стенде
            # это падает как «column does not exist» при первой же записи.
            "ALTER TABLE doc_kinds ADD COLUMN IF NOT EXISTS route JSONB",
            "ALTER TABLE doc_kinds ADD COLUMN IF NOT EXISTS default_case_id UUID",
            "ALTER TABLE doc_cards ADD COLUMN IF NOT EXISTS case_id UUID",
            "ALTER TABLE doc_cards ADD COLUMN IF NOT EXISTS storage_until DATE",
            "ALTER TABLE doc_cards ADD COLUMN IF NOT EXISTS approval_status "
            "VARCHAR(15) NOT NULL DEFAULT 'none'",
            "ALTER TABLE doc_cards ADD COLUMN IF NOT EXISTS approval_round "
            "INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE doc_cards ADD COLUMN IF NOT EXISTS verify_token VARCHAR(64)",
            "UPDATE doc_cards SET verify_token = replace(gen_random_uuid()::text, '-', '') "
            "WHERE reg_number IS NOT NULL AND verify_token IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_cards_verify_token "
            "ON doc_cards (verify_token) WHERE verify_token IS NOT NULL",
            # До выбора юрлица UI заводил карточки без organization_id. Если у
            # компании одно юрлицо, двусмысленности нет: переносим карточки и
            # продолжаем прежний счётчик уже под ключом этого юрлица.
            "WITH single_org AS (SELECT company_id, "
            "(array_agg(id ORDER BY id))[1]::text AS org_id "
            "FROM organizations GROUP BY company_id HAVING count(*) = 1), "
            "migrated AS (SELECT counter.company_id, counter.scope_key, "
            "split_part(counter.scope_key, '|', 1) || '|' || single_org.org_id || "
            "'|' || split_part(counter.scope_key, '|', 3) AS new_scope, "
            "counter.next_value FROM doc_counters AS counter "
            "JOIN single_org ON single_org.company_id = counter.company_id "
            "JOIN doc_kinds AS kind ON kind.company_id = counter.company_id "
            "AND kind.code = split_part(counter.scope_key, '|', 1) "
            "WHERE kind.number_scope LIKE '%org%' "
            "AND split_part(counter.scope_key, '|', 2) = '-') "
            "INSERT INTO doc_counters (company_id, scope_key, next_value) "
            "SELECT company_id, new_scope, next_value FROM migrated "
            "ON CONFLICT (company_id, scope_key) DO UPDATE SET next_value = "
            "GREATEST(doc_counters.next_value, EXCLUDED.next_value)",
            "WITH single_org AS (SELECT company_id FROM organizations "
            "GROUP BY company_id HAVING count(*) = 1) DELETE FROM doc_counters AS counter "
            "USING single_org, doc_kinds AS kind WHERE single_org.company_id = counter.company_id "
            "AND kind.company_id = counter.company_id "
            "AND kind.code = split_part(counter.scope_key, '|', 1) "
            "AND kind.number_scope LIKE '%org%' "
            "AND split_part(counter.scope_key, '|', 2) = '-'",
            "WITH single_org AS (SELECT company_id, "
            "(array_agg(id ORDER BY id))[1] AS organization_id "
            "FROM organizations GROUP BY company_id HAVING count(*) = 1) "
            "UPDATE doc_cards AS card SET organization_id = single_org.organization_id "
            "FROM single_org WHERE card.company_id = single_org.company_id "
            "AND card.organization_id IS NULL",
            # Видимый номер уникален внутри юрлица. У разных юрлиц свои журналы и
            # счётчики; прежний индекс по компании ошибочно запрещал им одинаковый
            # номер. NULL сводим к нулевому UUID, чтобы документы без юрлица тоже
            # не задваивались.
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname = 'uq_doc_cards_reg_number' "
            "AND indexdef NOT LIKE '%COALESCE%') THEN "
            "EXECUTE 'DROP INDEX ' || quote_ident(current_schema()) || "
            "'.uq_doc_cards_reg_number'; END IF; END $$",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_cards_reg_number "
            "ON doc_cards (company_id, COALESCE(organization_id, "
            "'00000000-0000-0000-0000-000000000000'::uuid), reg_number) "
            "WHERE reg_number IS NOT NULL",
            "ALTER TABLE doc_share_links ADD COLUMN IF NOT EXISTS version_snapshot JSONB",
            "ALTER TABLE doc_share_links ADD COLUMN IF NOT EXISTS card_snapshot JSONB",
            # Старую ссылку нельзя достоверно связать с редакцией задним числом.
            # Сохраняем её в аудите, но для показа требуется перевыпуск.
            "UPDATE doc_share_links SET revoked = true "
            "WHERE revoked = false AND (version_snapshot IS NULL OR card_snapshot IS NULL)",
            # Исправляем возможный старый дубль current до включения страховочного
            # индекса. Текущей остаётся последняя живая редакция каждой роли.
            "WITH ranked AS (SELECT id, row_number() OVER (PARTITION BY doc_id, role "
            "ORDER BY revision DESC, uploaded_at DESC, id DESC) AS position "
            "FROM doc_versions WHERE is_current = true AND tombstoned_at IS NULL) "
            "UPDATE doc_versions AS version SET is_current = false FROM ranked "
            "WHERE version.id = ranked.id AND ranked.position > 1",
            "WITH state AS (SELECT card.id, COALESCE(max(version.revision) FILTER (WHERE "
            "version.role = 'body' AND version.is_current = true "
            "AND version.tombstoned_at IS NULL), 0) AS current_revision, "
            "bool_or(version.id IS NOT NULL AND version.tombstoned_at IS NULL) AS has_files "
            "FROM doc_cards AS card LEFT JOIN doc_versions AS version "
            "ON version.doc_id = card.id GROUP BY card.id) "
            "UPDATE doc_cards AS card SET current_revision = state.current_revision, "
            "has_files = state.has_files FROM state WHERE card.id = state.id "
            "AND (card.current_revision IS DISTINCT FROM state.current_revision "
            "OR card.has_files IS DISTINCT FROM state.has_files)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_versions_current_role "
            "ON doc_versions (doc_id, role) WHERE is_current = true "
            "AND tombstoned_at IS NULL",
            # Волна достоверности: существующая таблица виз должна научиться
            # отличать будущий шаг от активного и хранить пакет согласования.
            "ALTER TABLE doc_approvals ADD COLUMN IF NOT EXISTS sla_hours INTEGER",
            "ALTER TABLE doc_approvals ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ",
            "ALTER TABLE doc_approvals ADD COLUMN IF NOT EXISTS activation_estimated "
            "BOOLEAN NOT NULL DEFAULT false",
            # У старых строк отдельного события активации нет. SLA даёт точный
            # момент, для остальных остаётся консервативная оценка от запуска
            # круга; новые строки всегда получают activated_at в движке.
            "UPDATE doc_approvals SET activated_at = CASE "
            "WHEN due_at IS NOT NULL AND sla_hours IS NOT NULL "
            "THEN due_at - (sla_hours * INTERVAL '1 hour') ELSE created_at END, "
            "activation_estimated = NOT (due_at IS NOT NULL AND sla_hours IS NOT NULL) "
            "WHERE activated_at IS NULL AND status IN ('pending','approved','rejected')",
            "ALTER TABLE doc_approvals ADD COLUMN IF NOT EXISTS document_snapshot JSONB",
            "ALTER TABLE doc_approvals ADD COLUMN IF NOT EXISTS snapshot_sha256 CHAR(64)",
            "CREATE INDEX IF NOT EXISTS idx_doc_approvals_report "
            "ON doc_approvals (company_id, round, created_at, doc_id)",
            "CREATE INDEX IF NOT EXISTS idx_doc_approvals_pending_due "
            "ON doc_approvals (company_id, due_at) WHERE status = 'pending'",
            # Волна 4: механизмы трекера работают и с документами. Шаблон умеет
            # порождать документ, время тратится на документ, у представлений
            # появилась область. Таблицы уже существуют — значит только ALTER.
            "ALTER TABLE task_templates ADD COLUMN IF NOT EXISTS doc_kind_id UUID",
            "ALTER TABLE task_work_items ADD COLUMN IF NOT EXISTS doc_id UUID",
            "ALTER TABLE task_work_items ALTER COLUMN task_id DROP NOT NULL",
            "ALTER TABLE task_views ADD COLUMN IF NOT EXISTS list_scope "
            "VARCHAR(10) NOT NULL DEFAULT 'task'",
            # Волна 5: обмен с корпоративными системами головной компании.
            # Таблицы новые, их заводит create_all; индекс по неразобранным
            # кандидатам нужен экрану приёма.
            "CREATE INDEX IF NOT EXISTS idx_doc_inbox_new ON doc_inbox_items "
            "(company_id, status, found_at)",
            # Полнотекстовый поиск по содержимому редакций. Колонка нужна через
            # ALTER: doc_versions уже есть на обоих пилотах.
            "ALTER TABLE doc_versions ADD COLUMN IF NOT EXISTS content_text TEXT",
            "CREATE INDEX IF NOT EXISTS idx_doc_versions_text ON doc_versions "
            "USING gin (to_tsvector('russian', coalesce(content_text, '')))",
            # Волна 7: напоминания об ознакомлении и управляемое расписание
            # приёма из СЭД. По умолчанию автоскан выключен до ручной обкатки.
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS reminder_attempted_at TIMESTAMPTZ",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS reminder_error VARCHAR(500)",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS document_snapshot JSONB",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS snapshot_sha256 CHAR(64)",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS reason_ref UUID",
            "ALTER TABLE doc_acquaints ADD COLUMN IF NOT EXISTS reason_name VARCHAR(160)",
            "ALTER TABLE doc_acquaints DROP CONSTRAINT IF EXISTS uq_doc_acquaints_person",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_acquaints_snapshot "
            "ON doc_acquaints (doc_id, user_id, snapshot_sha256) "
            "WHERE snapshot_sha256 IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_doc_acquaints_due ON doc_acquaints "
            "(company_id, status, due_at)",
            "ALTER TABLE doc_exchange_targets ADD COLUMN IF NOT EXISTS scan_enabled "
            "BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE doc_exchange_targets ADD COLUMN IF NOT EXISTS scan_interval_min "
            "INTEGER NOT NULL DEFAULT 30",
            "ALTER TABLE doc_exchange_targets ADD COLUMN IF NOT EXISTS scan_cursor VARCHAR(500)",
            # Повторно прочитанное письмо не должно завести вторую карточку.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_cards_mail_source "
            "ON doc_cards (company_id, source_ref) WHERE source = 'mail' "
            "AND source_ref IS NOT NULL",
            "ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS route_error VARCHAR(500)",
            "ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS route_attempts "
            "INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS route_attempted_at TIMESTAMPTZ",
            # Старые конкурентные дубли сохраняем, но явно маркируем отдельным
            # идентификатором; после этого инвариант БД создаётся безусловно.
            "WITH ranked AS (SELECT id, row_number() OVER (PARTITION BY company_id, "
            "message_id ORDER BY created_at, id) AS position FROM mail_messages "
            "WHERE message_id IS NOT NULL) UPDATE mail_messages AS message SET "
            "message_id = left(message.message_id, 430) || '#legacy-duplicate-' || "
            "message.id::text FROM ranked WHERE ranked.id = message.id "
            "AND ranked.position > 1",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_messages_company_msgid "
            "ON mail_messages (company_id, message_id) WHERE message_id IS NOT NULL",
        ):
            await conn.execute(_sa.text(stmt))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency — асинхронная сессия БД."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
