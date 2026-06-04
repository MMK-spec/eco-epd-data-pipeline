TRUNCATE TABLE mart.eco_epd;

WITH latest_run AS (
    SELECT run_id
    FROM staging.pipeline_runs
    WHERE status = 'success'
    ORDER BY fetched_at DESC
    LIMIT 1
),
normalized AS (
    SELECT
        e.*,
        COALESCE(
            NULLIF(BTRIM(e.name_en), ''),
            NULLIF(BTRIM(e.name_no), ''),
            NULLIF(BTRIM(e.name_da), ''),
            NULLIF(BTRIM(e.name_sv), '')
        ) AS name,
        CASE
            WHEN e.gwp_fossil_a1a3 IS NOT NULL
             AND e.gwp_biogenic_a1a3 IS NOT NULL
             AND e.gwp_fossil_a1a3 < e.gwp_biogenic_a1a3
                THEN e.gwp_fossil_a1a3
            ELSE e.gwp_biogenic_a1a3
        END AS gwp_biogenic_a1a3_normalized,
        CASE
            WHEN e.gwp_fossil_a1a3 IS NOT NULL
             AND e.gwp_biogenic_a1a3 IS NOT NULL
             AND e.gwp_fossil_a1a3 < e.gwp_biogenic_a1a3
                THEN e.gwp_biogenic_a1a3
            ELSE e.gwp_fossil_a1a3
        END AS gwp_fossil_a1a3_normalized
    FROM staging.eco_epd_raw AS e
    INNER JOIN latest_run AS r
        ON e.run_id = r.run_id
)
INSERT INTO mart.eco_epd (
    run_id,
    uuid,
    version,
    location_code,
    name,
    reference_year,
    valid_until,
    declaration_owner,
    registration_authority,
    publication_date,
    quantity,
    ref_unit,
    gwp_total_a1a3,
    gwp_biogenic_a1a3,
    gwp_fossil_a1a3,
    gwp_fossil_a1a3_assumed,
    gwp_luluc_a1a3,
    htpnc_a1a3,
    gwp_control,
    fetched_at,
    source_url
)
SELECT
    n.run_id,
    n.uuid,
    n.version,
    n.location_code,
    n.name,
    n.reference_year,
    n.valid_until,
    n.declaration_owner,
    n.registration_authority,
    n.publication_date,

    GREATEST(
        COALESCE(n.ref_quantity, 0),
        COALESCE(n.mass_kg, 0)
    ) AS quantity,

    n.ref_unit,

    n.gwp_total_a1a3,
    n.gwp_biogenic_a1a3_normalized AS gwp_biogenic_a1a3,
    n.gwp_fossil_a1a3_normalized AS gwp_fossil_a1a3,

    CASE
        WHEN n.ref_unit = 'kg'
        AND n.gwp_fossil_a1a3_normalized > 0
        AND n.gwp_fossil_a1a3_normalized < 10
        THEN n.gwp_fossil_a1a3_normalized * 1000
        ELSE n.gwp_fossil_a1a3_normalized
    END AS gwp_fossil_a1a3_assumed,

    n.gwp_luluc_a1a3,
    n.htpnc_a1a3,

    n.gwp_total_a1a3
        - n.gwp_biogenic_a1a3_normalized
        - n.gwp_fossil_a1a3_normalized
        - n.gwp_luluc_a1a3 AS gwp_control,


    n.fetched_at,
    n.source_url
FROM normalized AS n;
