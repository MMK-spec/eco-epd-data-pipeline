TRUNCATE TABLE mart.eco_epd;

WITH latest_run AS (
    SELECT run_id
    FROM staging.pipeline_runs
    WHERE status = 'success'
    ORDER BY fetched_at DESC
    LIMIT 1
)
INSERT INTO mart.eco_epd (
    run_id,
    uuid,
    version,
    location_code,
    reference_year,
    valid_until,
    declaration_owner,
    publication_date,
    quantity,
    ref_unit,
    gwp_total_a1a3,
    gwp_biogenic_a1a3,
    gwp_fossil_a1a3,
    gwp_luluc_a1a3,
    gwp_control,
    fetched_at,
    source_url
)
SELECT
    e.run_id,
    e.uuid,
    e.version,
    e.location_code,
    e.reference_year,
    e.valid_until,
    e.declaration_owner,
    e.publication_date,

    GREATEST(
        COALESCE(e.ref_quantity, 0),
        COALESCE(e.mass_kg, 0)
    ) AS quantity,

    e.ref_unit,

    e.gwp_total_a1a3,
    e.gwp_biogenic_a1a3,
    e.gwp_fossil_a1a3,
    e.gwp_luluc_a1a3,

    e.gwp_total_a1a3
        - e.gwp_biogenic_a1a3
        - e.gwp_fossil_a1a3
        - e.gwp_luluc_a1a3 AS gwp_control,

    e.fetched_at,
    e.source_url
FROM staging.eco_epd_raw AS e
INNER JOIN latest_run AS r
    ON e.run_id = r.run_id;
