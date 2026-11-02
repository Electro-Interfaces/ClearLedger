-- Literal version1 prerequisites; Calendar is legacy20. No managed revision DDL.

CREATE OR REPLACE FUNCTION phone_to_e164(raw text) RETURNS varchar
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $fn$
DECLARE
  part text;
  d text;
BEGIN
  IF raw IS NULL THEN
    RETURN NULL;
  END IF;
  FOREACH part IN ARRAY regexp_split_to_array(raw, '[,;/]') LOOP
    part := regexp_replace(part, '(^|[^а-яёa-z])(доб|ext|вн).*$', '\1', 'i');
    d := regexp_replace(part, '[^0-9]', '', 'g');
    IF length(d) = 11 AND left(d, 1) IN ('7', '8') THEN
      RETURN '+7' || right(d, 10);
    ELSIF length(d) = 10 AND position('+' IN part) = 0 THEN
      RETURN '+7' || d;
    ELSIF position('+' IN part) > 0 AND length(d) BETWEEN 11 AND 15 THEN
      RETURN '+' || d;
    END IF;
  END LOOP;
  RETURN NULL;
END
$fn$;

CREATE TABLE core.companies (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(50) NOT NULL,
    short_name character varying(100),
    profile_id character varying(50) NOT NULL,
    color character varying(20),
    inn character varying(20),
    tz character varying(64) NOT NULL DEFAULT 'Europe/Moscow'::character varying,
    cloud_api_key character varying(128),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    customization jsonb,
    PRIMARY KEY (id),
    CONSTRAINT companies_slug_key UNIQUE (slug),
    CONSTRAINT companies_cloud_api_key_key UNIQUE (cloud_api_key)
);

CREATE TABLE core.users (
    id uuid NOT NULL,
    company_id uuid REFERENCES core.companies (id) ON DELETE NO ACTION,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    station_pin_hash character varying(255),
    name character varying(255) NOT NULL,
    role character varying(50) NOT NULL,
    is_superadmin boolean NOT NULL DEFAULT false,
    reset_token_hash character varying(64),
    reset_token_expires timestamp with time zone,
    last_seen_at timestamp with time zone,
    avatar_url character varying(300),
    phone_mobile character varying(40),
    phone_office character varying(40),
    phone_mobile_e164 character varying(16) GENERATED ALWAYS AS (phone_to_e164(phone_mobile)) STORED,
    phone_office_e164 character varying(16) GENERATED ALWAYS AS (phone_to_e164(phone_office)) STORED,
    mail_only boolean NOT NULL DEFAULT false,
    task_notify jsonb,
    email_notify jsonb,
    away_from date,
    away_to date,
    token_version integer NOT NULL DEFAULT 0,
    failed_logins integer NOT NULL DEFAULT 0,
    locked_until timestamp with time zone,
    totp_secret text,
    totp_enabled boolean NOT NULL DEFAULT false,
    tz character varying(64) NOT NULL DEFAULT 'Europe/Moscow'::character varying,
    work_start time without time zone NOT NULL DEFAULT '09:00:00'::time without time zone,
    work_end time without time zone NOT NULL DEFAULT '18:00:00'::time without time zone,
    calendar_feed_token character varying(64),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT users_email_key UNIQUE (email)
);

CREATE UNIQUE INDEX ix_users_calendar_feed_token ON core.users (calendar_feed_token);

CREATE TABLE core.organizations (
    id uuid NOT NULL,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE NO ACTION,
    inn character varying(20) NOT NULL,
    kpp character varying(20),
    ogrn character varying(20),
    name character varying(500) NOT NULL,
    bank_account character varying(30),
    bank_bik character varying(12),
    vid character varying(40),
    full_name character varying(500),
    prefix character varying(10),
    okpo character varying(20),
    reg_date character varying(20),
    okved character varying(20),
    oktmo character varying(20),
    okato character varying(20),
    okopf character varying(20),
    okfs character varying(20),
    registration_cert character varying(300),
    ifns_code character varying(10),
    ifns_name character varying(300),
    pfr_reg_number character varying(30),
    fss_reg_number character varying(30),
    fss_subordination character varying(10),
    legal_address text,
    actual_address text,
    postal_address text,
    phone character varying(100),
    fax character varying(100),
    email character varying(255),
    director_name character varying(255),
    director_position character varying(150),
    accountant_name character varying(255),
    cashier_name character varying(255),
    external_ref character varying(36),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE core.eco_apps (
    id uuid NOT NULL,
    code character varying(40) NOT NULL,
    name character varying(120) NOT NULL,
    description text,
    base_url character varying(300),
    icon character varying(60),
    kind character varying(20) NOT NULL,
    sort integer NOT NULL,
    is_active boolean NOT NULL,
    config jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT eco_apps_code_key UNIQUE (code)
);

CREATE TABLE core.eco_company_apps (
    id uuid NOT NULL,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE CASCADE,
    app_id uuid NOT NULL REFERENCES core.eco_apps (id) ON DELETE CASCADE,
    enabled boolean NOT NULL,
    config jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX ix_eco_company_apps_company_id ON core.eco_company_apps (company_id);

CREATE UNIQUE INDEX uq_eco_company_app ON core.eco_company_apps (company_id, app_id);

CREATE TABLE core.partner_clients (
    id character varying(64) NOT NULL,
    app_id uuid NOT NULL REFERENCES core.eco_apps (id) ON DELETE CASCADE,
    owner_company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE CASCADE,
    redirect_uris jsonb NOT NULL,
    allowed_scopes jsonb NOT NULL,
    auth_method character varying(30) NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT ck_partner_client_auth CHECK (auth_method IN ('none','client_secret_basic')),
    CONSTRAINT partner_clients_app_id_key UNIQUE (app_id)
);

CREATE TABLE core.partner_installations (
    id uuid NOT NULL REFERENCES core.eco_company_apps (id) ON DELETE CASCADE,
    client_id character varying(64) NOT NULL REFERENCES core.partner_clients (id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE CASCADE,
    approved boolean NOT NULL,
    scopes jsonb NOT NULL,
    all_locations boolean NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_partner_install_client_company UNIQUE (id, client_id, company_id)
);

CREATE INDEX ix_partner_installations_client_id ON core.partner_installations (client_id);

CREATE TABLE core.calendar_events (
    id uuid NOT NULL,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE CASCADE,
    organizer_id uuid NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
    title character varying(300) NOT NULL,
    description text,
    starts_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    all_day boolean NOT NULL,
    tz character varying(64) NOT NULL,
    location character varying(300),
    conference_url text,
    visibility character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    cancel_reason character varying(300),
    subject_ref character varying(120),
    recurrence jsonb,
    recurrence_until date,
    series_id uuid REFERENCES core.calendar_events (id) ON DELETE CASCADE,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT ck_calendar_event_span CHECK (ends_at > starts_at)
);

CREATE INDEX ix_calendar_events_company_id ON core.calendar_events (company_id);

CREATE INDEX ix_calendar_events_organizer_id ON core.calendar_events (organizer_id);

CREATE INDEX ix_calendar_events_series_id ON core.calendar_events (series_id);

CREATE INDEX ix_calendar_events_span ON core.calendar_events (company_id, starts_at, ends_at);

CREATE TABLE core.company_roles (
    id uuid NOT NULL,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE CASCADE,
    name character varying(100) NOT NULL,
    modules jsonb,
    is_system boolean NOT NULL DEFAULT false,
    chat_scope character varying(40),
    app_roles jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX ix_company_roles_company_id ON core.company_roles (company_id);

CREATE TABLE core.pulse_views (
    id uuid NOT NULL,
    company_id uuid NOT NULL REFERENCES core.companies (id) ON DELETE NO ACTION,
    name character varying(200) NOT NULL,
    audience character varying(300) NOT NULL,
    organization_id uuid REFERENCES core.organizations (id) ON DELETE NO ACTION,
    period character varying(20) NOT NULL,
    owner_name character varying(200),
    note text NOT NULL,
    status character varying(20) NOT NULL,
    feedback_mode character varying(20) NOT NULL,
    feedback_room_id uuid,
    feedback_assignee_id uuid,
    created_by character varying(200),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX idx_pulse_views_company ON core.pulse_views (company_id, status);
