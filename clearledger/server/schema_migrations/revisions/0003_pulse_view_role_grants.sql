CREATE TABLE core.pulse_view_role_grants (
    view_id uuid NOT NULL REFERENCES core.pulse_views(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES core.company_roles(id) ON DELETE CASCADE,
    PRIMARY KEY (view_id, role_id)
);
