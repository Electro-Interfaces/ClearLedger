CREATE TABLE core.core_schema_versions (
    revision text PRIMARY KEY,
    ordinal integer NOT NULL UNIQUE,
    parent_revision text,
    artifact_sha256 char(64) NOT NULL,
    contract_sha256 char(64) NOT NULL,
    predecessor_sha256 char(64),
    action text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text NOT NULL,
    app_commit char(40) NOT NULL,
    runner_format integer NOT NULL,
    CONSTRAINT ck_core_schema_action CHECK (action = 'created'::text OR action = 'adopted'::text)
);
