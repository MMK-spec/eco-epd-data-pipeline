CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS quality;

CREATE TABLE IF NOT EXISTS staging.pipeline_runs (
    run_id uuid PRIMARY KEY,
    fetched_at timestamptz NOT NULL,
    source_name text NOT NULL,
    forecast_days integer NOT NULL,
    status text NOT NULL,
    message text
);

CREATE TABLE IF NOT EXISTS staging.eco_epd_raw (
    run_id uuid NOT NULL REFERENCES staging.pipeline_runs (run_id),

    uuid text NOT NULL,
    version text,

    location_code text,

    name_no text,
    name_en text,
    name_da text,
    name_sv text,

    compliance text,

    reference_year integer,
    valid_until date,

    declaration_owner text,

    publication_date date,
    registration_number text,
    registration_authority text,

    ref_quantity numeric(18, 6),
    ref_unit text,
    mass_kg numeric(18, 6),

    carbon_content_biogenic_kg numeric(18, 6),
    carbon_content_biogenic_packaging_kg numeric(18, 6),

    gwp_total_a1a3 numeric(18, 6),
    gwp_biogenic_a1a3 numeric(18, 6),
    gwp_fossil_a1a3 numeric(18, 6),
    gwp_fossil_a1a3_assumed numeric(18, 6),
    gwp_luluc_a1a3 numeric(18, 6),
    registration_authority text,
    htpnc_a1a3 numeric(18, 6),

    fetched_at timestamptz NOT NULL,
    source_url text NOT NULL,

    PRIMARY KEY (run_id, uuid)
);

CREATE TABLE IF NOT EXISTS mart.eco_epd (
    run_id uuid NOT NULL REFERENCES staging.pipeline_runs (run_id),

    uuid text NOT NULL,
    version text,

    location_code text,
    
    name text,

    reference_year integer,
    valid_until date,

    declaration_owner text,
    registration_authority text,
    publication_date date,

    quantity numeric(18, 6),
    ref_unit text,

    gwp_total_a1a3 numeric(18, 6),
    gwp_biogenic_a1a3 numeric(18, 6),
    gwp_fossil_a1a3 numeric(18, 6),
    gwp_luluc_a1a3 numeric(18, 6),
    htpnc_a1a3 numeric(18, 6),
    gwp_control numeric(18, 6),

    fetched_at timestamptz NOT NULL,
    source_url text NOT NULL,

    PRIMARY KEY (run_id, uuid)
);

CREATE TABLE IF NOT EXISTS quality.test_results (
    test_run_at timestamptz NOT NULL DEFAULT now(),
    test_name text NOT NULL,
    status text NOT NULL,
    failed_rows integer NOT NULL,
    message text NOT NULL
);

CREATE OR REPLACE VIEW mart.latest_pipeline_run AS
SELECT
    run_id,
    fetched_at,
    source_name,
    forecast_days,
    status,
    message
FROM staging.pipeline_runs
WHERE status = 'success'
ORDER BY fetched_at DESC
LIMIT 1;

CREATE OR REPLACE VIEW mart.latest_eco_epd AS
SELECT e.*
FROM mart.eco_epd AS e
INNER JOIN mart.latest_pipeline_run AS r
    ON e.run_id = r.run_id;
