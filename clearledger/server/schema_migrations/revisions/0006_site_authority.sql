-- Explicit revision0006; Site writers OFF; no approval/backfill/adoption.
ALTER TABLE core.ezs_sites ADD CONSTRAINT uq_site_authority_site_company UNIQUE (company_id,id);
ALTER TABLE core.organizations ADD CONSTRAINT uq_site_authority_org_company UNIQUE (company_id,id);
CREATE TABLE core.site_authority_contexts (
    company_id uuid NOT NULL,
    site_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    approved boolean NOT NULL DEFAULT false,
    revoked boolean NOT NULL DEFAULT true,
    policy_generation integer NOT NULL DEFAULT 1,
    CONSTRAINT site_authority_contexts_pkey PRIMARY KEY (company_id,site_id),
    CONSTRAINT ck_site_context_generation CHECK (policy_generation > 0),
    CONSTRAINT fk_site_context_site FOREIGN KEY (company_id,site_id) REFERENCES core.ezs_sites (company_id,id) ON DELETE CASCADE,
    CONSTRAINT fk_site_context_organization FOREIGN KEY (company_id,organization_id) REFERENCES core.organizations (company_id,id) ON DELETE CASCADE
);
CREATE TABLE core.site_user_permissions (
    company_id uuid NOT NULL,
    site_id uuid NOT NULL,
    user_id uuid NOT NULL,
    action varchar(32) NOT NULL,
    approved boolean NOT NULL DEFAULT false,
    CONSTRAINT site_user_permissions_pkey PRIMARY KEY (company_id,site_id,user_id,action),
    CONSTRAINT ck_site_permission_action CHECK (action='site.read' OR action='site.link_edit' OR action='contract.create' OR action='document.create' OR action='document.read' OR action='document.edit' OR action='document.download' OR action='document.print' OR action='document.export' OR action='document.send' OR action='document.approve' OR action='document.sign' OR action='document.archive' OR action='document.manage_acl'),
    CONSTRAINT fk_site_permission_context FOREIGN KEY (company_id,site_id) REFERENCES core.site_authority_contexts (company_id,site_id) ON DELETE CASCADE,
    CONSTRAINT fk_site_permission_membership FOREIGN KEY (user_id,company_id) REFERENCES core.user_companies (user_id,company_id) ON DELETE CASCADE
);
ALTER TABLE core.partner_resource_items ADD COLUMN site_id uuid;
ALTER TABLE core.partner_resource_items ADD CONSTRAINT fk_partner_resource_site FOREIGN KEY (site_id) REFERENCES core.ezs_sites(id) ON DELETE CASCADE;
ALTER TABLE core.partner_resource_scopes DROP CONSTRAINT ck_partner_resource_kind;
ALTER TABLE core.partner_resource_scopes ADD CONSTRAINT ck_partner_resource_kind CHECK (kind='objects' OR kind='equipment' OR kind='counterparties' OR kind='contracts' OR kind='documents' OR kind='sites');
ALTER TABLE core.partner_resource_scopes ADD CONSTRAINT ck_partner_sites_mode CHECK (kind <> 'sites' OR mode='SET' OR mode='EMPTY');
ALTER TABLE core.partner_resource_items DROP CONSTRAINT ck_partner_resource_one_id;
ALTER TABLE core.partner_resource_items ADD CONSTRAINT ck_partner_resource_one_id CHECK (num_nonnulls(object_id,equipment_id,counterparty_id,contract_id,document_id,site_id)=1);
ALTER TABLE core.partner_resource_items DROP CONSTRAINT ck_partner_resource_typed_id;
ALTER TABLE core.partner_resource_items ADD CONSTRAINT ck_partner_resource_typed_id CHECK ((kind='objects' AND object_id IS NOT NULL) OR (kind='equipment' AND equipment_id IS NOT NULL) OR (kind='counterparties' AND counterparty_id IS NOT NULL) OR (kind='contracts' AND contract_id IS NOT NULL) OR (kind='documents' AND document_id IS NOT NULL) OR (kind='sites' AND site_id IS NOT NULL));
