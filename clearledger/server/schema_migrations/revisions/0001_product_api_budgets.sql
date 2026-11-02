CREATE TABLE core.product_api_budgets (
    company_id uuid NOT NULL,
    installation_id uuid NOT NULL,
    client_id varchar(64) NOT NULL,
    used integer NOT NULL,
    reset_at timestamptz NOT NULL,
    request_limit integer NOT NULL,
    window_seconds integer NOT NULL,
    PRIMARY KEY (company_id, installation_id, client_id),
    FOREIGN KEY (installation_id, client_id, company_id)
        REFERENCES core.partner_installations (id, client_id, company_id) ON DELETE CASCADE,
    CONSTRAINT ck_product_budget_limit CHECK (request_limit BETWEEN 1 AND 1000000),
    CONSTRAINT ck_product_budget_window CHECK (window_seconds BETWEEN 1 AND 3600),
    CONSTRAINT ck_product_budget_used CHECK (used BETWEEN 1 AND request_limit + 1)
);
CREATE INDEX ix_product_api_budgets_reset ON core.product_api_budgets (reset_at);
