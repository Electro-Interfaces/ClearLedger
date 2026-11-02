-- Revision0004: аддитивный SOURCE-пакет, только explicit runner; без adoption/repair.

CREATE TABLE core.partner_contract_create_profiles (
    id uuid NOT NULL,
    installation_id uuid NOT NULL,
    client_id varchar(64) NOT NULL,
    company_id uuid NOT NULL,
    user_enabled boolean NOT NULL DEFAULT false,
    service_enabled boolean NOT NULL DEFAULT false,
    revoked boolean NOT NULL DEFAULT false,
    policy_generation bigint NOT NULL DEFAULT 1,
    CONSTRAINT partner_contract_create_profiles_pkey PRIMARY KEY (id),
    CONSTRAINT uq_pc_profile_installation UNIQUE (installation_id),
    CONSTRAINT ck_pc_profile_generation CHECK (policy_generation > 0),
    CONSTRAINT fk_pc_profile_installation FOREIGN KEY (installation_id, client_id, company_id) REFERENCES core.partner_installations (id, client_id, company_id) ON DELETE CASCADE
);

CREATE INDEX ix_pc_profile_company ON core.partner_contract_create_profiles (company_id, installation_id);

REVOKE ALL ON TABLE core.partner_contract_create_profiles FROM PUBLIC;

CREATE TABLE core.partner_contract_create_principals (
    id uuid NOT NULL,
    profile_id uuid NOT NULL,
    actor_kind text NOT NULL,
    user_id uuid,
    machine_grant_id uuid,
    CONSTRAINT partner_contract_create_principals_pkey PRIMARY KEY (id),
    CONSTRAINT ck_pc_principal_actor CHECK ((actor_kind = 'user' AND user_id IS NOT NULL AND machine_grant_id IS NULL) OR (actor_kind = 'machine' AND user_id IS NULL AND machine_grant_id IS NOT NULL)),
    CONSTRAINT fk_pc_principal_profile FOREIGN KEY (profile_id) REFERENCES core.partner_contract_create_profiles (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_principal_user FOREIGN KEY (user_id) REFERENCES core.users (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_principal_grant FOREIGN KEY (machine_grant_id) REFERENCES core.partner_grants (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_pc_principal_user ON core.partner_contract_create_principals (profile_id, user_id) WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX uq_pc_principal_grant ON core.partner_contract_create_principals (profile_id, machine_grant_id) WHERE machine_grant_id IS NOT NULL;

REVOKE ALL ON TABLE core.partner_contract_create_principals FROM PUBLIC;

CREATE TABLE core.partner_contract_create_refs (
    id uuid NOT NULL,
    profile_id uuid NOT NULL,
    kind text NOT NULL,
    organization_id uuid,
    counterparty_id uuid,
    location_id varchar(40),
    CONSTRAINT partner_contract_create_refs_pkey PRIMARY KEY (id),
    CONSTRAINT ck_pc_ref_typed CHECK ((kind = 'organization' AND organization_id IS NOT NULL AND counterparty_id IS NULL AND location_id IS NULL) OR (kind = 'counterparty' AND organization_id IS NULL AND counterparty_id IS NOT NULL AND location_id IS NULL) OR (kind = 'location' AND organization_id IS NULL AND counterparty_id IS NULL AND location_id IS NOT NULL)),
    CONSTRAINT ck_pc_ref_location CHECK (location_id IS NULL OR location_id ~ '[^[:space:]]'),
    CONSTRAINT fk_pc_ref_profile FOREIGN KEY (profile_id) REFERENCES core.partner_contract_create_profiles (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_ref_org FOREIGN KEY (organization_id) REFERENCES core.organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_ref_cp FOREIGN KEY (counterparty_id) REFERENCES core.counterparties (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_ref_location FOREIGN KEY (location_id) REFERENCES core.service_locations (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_pc_ref_org ON core.partner_contract_create_refs (profile_id, organization_id) WHERE organization_id IS NOT NULL;

CREATE UNIQUE INDEX uq_pc_ref_cp ON core.partner_contract_create_refs (profile_id, counterparty_id) WHERE counterparty_id IS NOT NULL;

CREATE UNIQUE INDEX uq_pc_ref_location ON core.partner_contract_create_refs (profile_id, location_id) WHERE location_id IS NOT NULL;

REVOKE ALL ON TABLE core.partner_contract_create_refs FROM PUBLIC;

CREATE TABLE core.partner_contract_create_types (
    profile_id uuid NOT NULL,
    type_code text NOT NULL,
    CONSTRAINT partner_contract_create_types_pkey PRIMARY KEY (profile_id, type_code),
    CONSTRAINT ck_pc_type_code CHECK (type_code ~ '[^[:space:]]'),
    CONSTRAINT fk_pc_type_profile FOREIGN KEY (profile_id) REFERENCES core.partner_contract_create_profiles (id) ON DELETE CASCADE,
    CONSTRAINT fk_pc_type_code FOREIGN KEY (type_code) REFERENCES core.contract_types (code) ON DELETE CASCADE
);

REVOKE ALL ON TABLE core.partner_contract_create_types FROM PUBLIC;

CREATE TABLE core.partner_contract_success_intents (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    app_id uuid NOT NULL,
    installation_id uuid NOT NULL,
    original_grant_id uuid NOT NULL,
    create_profile_id uuid NOT NULL,
    client_id varchar(64) NOT NULL,
    operation text NOT NULL,
    creation_key uuid NOT NULL,
    actor_kind text NOT NULL,
    actor_key varchar(64) NOT NULL,
    current_user_id uuid,
    newborn_id uuid NOT NULL,
    current_contract_id uuid,
    request_hash char(64) NOT NULL,
    hash_version integer NOT NULL DEFAULT 1,
    created_organization_id uuid NOT NULL,
    created_counterparty_id uuid NOT NULL,
    created_type_code text NOT NULL,
    succeeded boolean NOT NULL DEFAULT true,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    created_txid text NOT NULL DEFAULT (pg_current_xact_id())::text,
    CONSTRAINT partner_contract_success_intents_pkey PRIMARY KEY (id),
    CONSTRAINT uq_pc_intent_namespace UNIQUE (company_id, app_id, installation_id, operation, creation_key),
    CONSTRAINT ck_pc_intent_operation CHECK (operation = 'createContract'),
    CONSTRAINT ck_pc_intent_success CHECK (succeeded),
    CONSTRAINT ck_pc_intent_hash_version CHECK (hash_version = 1),
    CONSTRAINT ck_pc_intent_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_pc_intent_text CHECK (client_id ~ '[^[:space:]]' AND created_type_code ~ '[^[:space:]]'),
    CONSTRAINT ck_pc_intent_actor CHECK ((actor_kind = 'user' AND actor_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND (current_user_id IS NULL OR actor_key = current_user_id::text)) OR (actor_kind = 'machine' AND actor_key = client_id AND current_user_id IS NULL)),
    CONSTRAINT ck_pc_intent_contract CHECK (current_contract_id IS NULL OR current_contract_id = newborn_id),
    CONSTRAINT fk_pc_intent_user FOREIGN KEY (current_user_id) REFERENCES core.users (id) ON DELETE SET NULL,
    CONSTRAINT fk_pc_intent_contract FOREIGN KEY (current_contract_id) REFERENCES core.contracts (id) ON DELETE SET NULL
);

CREATE INDEX ix_pc_success_principal_contract ON core.partner_contract_success_intents (company_id, installation_id, app_id, client_id, original_grant_id, actor_kind, actor_key, current_contract_id) WHERE succeeded AND current_contract_id IS NOT NULL;

CREATE INDEX ix_pc_success_profile ON core.partner_contract_success_intents (create_profile_id, company_id);

REVOKE ALL ON TABLE core.partner_contract_success_intents FROM PUBLIC;

CREATE TABLE core.partner_contract_intent_locations (
    intent_id uuid NOT NULL,
    location_id varchar(40) NOT NULL,
    CONSTRAINT partner_contract_intent_locations_pkey PRIMARY KEY (intent_id, location_id),
    CONSTRAINT ck_pc_intent_location CHECK (location_id ~ '[^[:space:]]'),
    CONSTRAINT fk_pc_intent_location FOREIGN KEY (intent_id) REFERENCES core.partner_contract_success_intents (id) ON DELETE CASCADE
);

REVOKE ALL ON TABLE core.partner_contract_intent_locations FROM PUBLIC;

CREATE FUNCTION core.pc_contract_success_immutable() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, core
AS $pc$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.current_contract_id IS NULL OR (NEW.actor_kind = 'user' AND NEW.current_user_id IS NULL) THEN
            RAISE EXCEPTION 'partner contract success requires current result and actor at insert' USING ERRCODE = '23514';
        END IF;
        NEW.created_txid := pg_catalog.pg_current_xact_id()::text;
        RETURN NEW;
    END IF;
    IF (pg_catalog.to_jsonb(NEW) - 'current_user_id' - 'current_contract_id')
        IS DISTINCT FROM (pg_catalog.to_jsonb(OLD) - 'current_user_id' - 'current_contract_id')
        OR (NEW.current_user_id IS DISTINCT FROM OLD.current_user_id AND NEW.current_user_id IS NOT NULL)
        OR (NEW.current_contract_id IS DISTINCT FROM OLD.current_contract_id AND NEW.current_contract_id IS NOT NULL) THEN
        RAISE EXCEPTION 'immutable partner contract success' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$pc$;

REVOKE ALL ON FUNCTION core.pc_contract_success_immutable() FROM PUBLIC;

CREATE FUNCTION core.pc_contract_locations_immutable() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, core
AS $pc$
DECLARE
    parent_txid text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM core.partner_contract_success_intents WHERE id = OLD.intent_id) THEN
            RAISE EXCEPTION 'immutable partner contract locations' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'immutable partner contract locations' USING ERRCODE = '23514';
    END IF;
    SELECT created_txid INTO parent_txid FROM core.partner_contract_success_intents WHERE id = NEW.intent_id;
    IF parent_txid IS DISTINCT FROM pg_catalog.pg_current_xact_id()::text THEN
        RAISE EXCEPTION 'partner contract locations must be inserted with success' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$pc$;

REVOKE ALL ON FUNCTION core.pc_contract_locations_immutable() FROM PUBLIC;

CREATE TRIGGER tr_pc_success_immutable BEFORE INSERT OR UPDATE ON core.partner_contract_success_intents
FOR EACH ROW EXECUTE FUNCTION core.pc_contract_success_immutable();

CREATE TRIGGER tr_pc_locations_immutable BEFORE INSERT OR UPDATE OR DELETE ON core.partner_contract_intent_locations
FOR EACH ROW EXECUTE FUNCTION core.pc_contract_locations_immutable();
