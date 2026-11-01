-- Revision0005: immutable V2 success storage only; never adoption or authority.
CREATE TABLE core.partner_contract_cycle_receipts (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    app_id uuid NOT NULL,
    installation_id uuid NOT NULL,
    operation text NOT NULL,
    command_key uuid NOT NULL,
    client_id varchar(64) NOT NULL,
    user_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    operation_version integer NOT NULL DEFAULT 2,
    request_hash text NOT NULL,
    hash_version integer NOT NULL DEFAULT 1,
    target_kind text NOT NULL,
    target_id uuid NOT NULL,
    result jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    created_txid text NOT NULL DEFAULT (pg_current_xact_id())::text,
    CONSTRAINT partner_contract_cycle_receipts_pkey PRIMARY KEY (id),
    CONSTRAINT uq_pcc_receipt_namespace UNIQUE (company_id, app_id, installation_id, operation, command_key),
    CONSTRAINT fk_pcc_receipt_company FOREIGN KEY (company_id) REFERENCES core.companies (id) ON DELETE RESTRICT,
    CONSTRAINT ck_pcc_receipt_client CHECK (length(client_id) > 0),
    CONSTRAINT ck_pcc_receipt_operation_version CHECK (operation_version = 2),
    CONSTRAINT ck_pcc_receipt_hash_version CHECK (hash_version = 1),
    CONSTRAINT ck_pcc_receipt_hash CHECK (length(request_hash) = 64 AND request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_pcc_receipt_target CHECK (
        (operation = 'v2.contract.create' AND target_kind = 'contract') OR
        (operation = 'v2.contract.patch' AND target_kind = 'contract') OR
        (operation = 'v2.contract.location.link' AND target_kind = 'contract') OR
        (operation = 'v2.term.create' AND target_kind = 'term') OR
        (operation = 'v2.term.version' AND target_kind = 'term') OR
        (operation = 'v2.term.coverage' AND target_kind = 'term') OR
        (operation = 'v2.site.contract.link' AND target_kind = 'site') OR
        (operation = 'v2.site.location.link' AND target_kind = 'site') OR
        (operation = 'v2.document.draft.create' AND target_kind = 'document') OR
        (operation = 'v2.document.contract.link' AND target_kind = 'document') OR
        (operation = 'v2.document.register' AND target_kind = 'document') OR
        (operation = 'v2.document.version.upload' AND target_kind = 'version')),
    CONSTRAINT ck_pcc_receipt_result_object CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT ck_pcc_receipt_result_bytes CHECK (octet_length(convert_to(result::text, 'UTF8')) <= 131072)
);

REVOKE ALL ON TABLE core.partner_contract_cycle_receipts FROM PUBLIC;

CREATE TABLE core.partner_contract_cycle_receipt_refs (
    id uuid NOT NULL,
    receipt_id uuid NOT NULL,
    kind text NOT NULL,
    uuid_value uuid,
    location_value text,
    CONSTRAINT partner_contract_cycle_receipt_refs_pkey PRIMARY KEY (id),
    CONSTRAINT fk_pcc_ref_receipt FOREIGN KEY (receipt_id) REFERENCES core.partner_contract_cycle_receipts (id) ON DELETE RESTRICT,
    CONSTRAINT ck_pcc_ref_typed CHECK (
        (kind = 'location' AND uuid_value IS NULL AND location_value IS NOT NULL) OR
        (kind = 'organization' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'counterparty' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'site' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'contract' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'term' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'document' AND uuid_value IS NOT NULL AND location_value IS NULL) OR
        (kind = 'version' AND uuid_value IS NOT NULL AND location_value IS NULL)),
    CONSTRAINT ck_pcc_ref_location CHECK (location_value IS NULL OR (length(location_value) > 0 AND length(location_value) <= 40))
);

CREATE UNIQUE INDEX uq_pcc_ref_uuid ON core.partner_contract_cycle_receipt_refs (receipt_id, kind, uuid_value) WHERE uuid_value IS NOT NULL;
CREATE UNIQUE INDEX uq_pcc_ref_location ON core.partner_contract_cycle_receipt_refs (receipt_id, kind, location_value) WHERE location_value IS NOT NULL;

REVOKE ALL ON TABLE core.partner_contract_cycle_receipt_refs FROM PUBLIC;

CREATE FUNCTION core.pcc_receipt_immutable() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, core
AS $pcc$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := pg_catalog.transaction_timestamp();
        NEW.created_txid := pg_catalog.pg_current_xact_id()::text;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'immutable contract cycle receipt' USING ERRCODE = '23514';
END;
$pcc$;

REVOKE ALL ON FUNCTION core.pcc_receipt_immutable() FROM PUBLIC;

CREATE FUNCTION core.pcc_ref_immutable() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, core
AS $pcc$
DECLARE
    parent_txid text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT created_txid INTO parent_txid FROM core.partner_contract_cycle_receipts WHERE id = NEW.receipt_id;
        IF parent_txid IS DISTINCT FROM pg_catalog.pg_current_xact_id()::text THEN
            RAISE EXCEPTION 'contract cycle refs require original top transaction' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'immutable contract cycle receipt ref' USING ERRCODE = '23514';
END;
$pcc$;

REVOKE ALL ON FUNCTION core.pcc_ref_immutable() FROM PUBLIC;

CREATE TRIGGER tr_pcc_receipt_immutable BEFORE INSERT OR UPDATE OR DELETE ON core.partner_contract_cycle_receipts
FOR EACH ROW EXECUTE FUNCTION core.pcc_receipt_immutable();
CREATE TRIGGER tr_pcc_receipt_truncate BEFORE TRUNCATE ON core.partner_contract_cycle_receipts
FOR EACH STATEMENT EXECUTE FUNCTION core.pcc_receipt_immutable();
CREATE TRIGGER tr_pcc_ref_immutable BEFORE INSERT OR UPDATE OR DELETE ON core.partner_contract_cycle_receipt_refs
FOR EACH ROW EXECUTE FUNCTION core.pcc_ref_immutable();
CREATE TRIGGER tr_pcc_ref_truncate BEFORE TRUNCATE ON core.partner_contract_cycle_receipt_refs
FOR EACH STATEMENT EXECUTE FUNCTION core.pcc_ref_immutable();
