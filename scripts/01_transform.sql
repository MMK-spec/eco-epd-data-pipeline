TRUNCATE TABLE
    mart.eco_epd;

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
    gwp_total_a2,
    gwp_biogenic_a2,
    gwp_fossil_a2,
    gwp_luluc_a2,
    gwp_control,
    fetched_at,
    source_url
)
SELECT
    run_id,
    uuid,
    version,
    location_code,
    reference_year,
    valid_until,
    declaration_owner,
    publication_date,

    GREATEST(
        COALESCE(ref_quantity, 0),
        COALESCE(mass_kg, 0)
    ) AS quantity,

    ref_unit,

    gwp_total_a1a3,
    gwp_biogenic_a1a3,
    gwp_fossil_a1a3,
    gwp_luluc_a1a3,

    (
        COALESCE(gwp_total_a1a3, 0)
        - COALESCE(gwp_biogenic_a1a3, 0)
        - COALESCE(gwp_fossil_a1a3, 0)
        - COALESCE(gwp_luluc_a1a3, 0)
    ) AS gwp_control,

    fetched_at,
    source_url
FROM staging.eco_epd_raw;
