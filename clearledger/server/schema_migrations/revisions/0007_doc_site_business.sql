-- Explicit additive revision7. No old date casts, rewrites, data fixes or writers.
ALTER TABLE core.contracts ADD COLUMN validity_kind varchar(16);
ALTER TABLE core.contracts ADD CONSTRAINT ck_contract_validity CHECK (CASE WHEN validity_kind IS NULL OR validity_kind = 'unknown' THEN true WHEN validity_kind = 'openEnded' THEN valid_until IS NULL WHEN validity_kind = 'until' THEN CASE WHEN date ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' AND substring(date,1,4) <> '0000' AND valid_until ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' AND substring(valid_until,1,4) <> '0000' THEN CASE WHEN substring(date,9,2)::integer <= EXTRACT(DAY FROM (pg_catalog.make_date(substring(date,1,4)::integer,substring(date,6,2)::integer,1) + interval '1 month - 1 day')) AND substring(valid_until,9,2)::integer <= EXTRACT(DAY FROM (pg_catalog.make_date(substring(valid_until,1,4)::integer,substring(valid_until,6,2)::integer,1) + interval '1 month - 1 day')) THEN valid_until::date >= date::date ELSE false END ELSE false END ELSE false END);
ALTER TABLE core.ops_contract_terms ADD COLUMN site_id uuid;
ALTER TABLE core.ops_contract_terms ADD CONSTRAINT ck_ops_term_site
    CHECK (site_id IS NULL OR (scope_type = 'site' AND location_id IS NULL));
ALTER TABLE core.ops_contract_terms ADD CONSTRAINT fk_ops_term_site
    FOREIGN KEY (company_id,site_id) REFERENCES core.ezs_sites(company_id,id);
DROP INDEX core.uq_ops_term;
CREATE UNIQUE INDEX uq_ops_term ON core.ops_contract_terms
    (contract_id,cost_item,coalesce(location_id,''),valid_from) WHERE site_id IS NULL;
CREATE UNIQUE INDEX uq_ops_term_site ON core.ops_contract_terms
    (company_id,contract_id,cost_item,site_id,valid_from) WHERE site_id IS NOT NULL;
ALTER TABLE core.site_authority_contexts ADD CONSTRAINT uq_site_context_organization
    UNIQUE (company_id,site_id,organization_id);
ALTER TABLE core.doc_cards ADD COLUMN site_id uuid;
ALTER TABLE core.doc_cards ADD CONSTRAINT ck_doc_cards_site
    CHECK (site_id IS NULL OR (object_id IS NULL AND organization_id IS NOT NULL));
ALTER TABLE core.doc_cards ADD CONSTRAINT fk_doc_cards_site_context
    FOREIGN KEY (company_id,site_id,organization_id)
    REFERENCES core.site_authority_contexts(company_id,site_id,organization_id);
