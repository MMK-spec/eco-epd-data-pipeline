TRUNCATE TABLE quality.test_results;

WITH latest_run AS (
    SELECT run_id
    FROM staging.pipeline_runs
    WHERE status = 'success'
    ORDER BY fetched_at DESC
    LIMIT 1
),
test_cases AS (

    SELECT
        'eco_epd_raw_has_rows' AS test_name,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM staging.eco_epd_raw AS w
                INNER JOIN latest_run AS r ON w.run_id = r.run_id
            )
                THEN 0
            ELSE 1
        END AS failed_rows,
        'Viimasel edukal laadimisel peab olema vähemalt üks rida.' AS message

    UNION ALL

    SELECT
        'eco_epd_no_empty_rows' AS test_name,
        COUNT(*)::integer AS failed_rows,
        'EPD kirjetel ei tohi puududa põhiandmed.' AS message
    FROM mart.eco_epd
    INNER JOIN latest_run AS r
       ON e.run_id = r.run_id
    WHERE uuid IS NULL
       OR quantity IS NULL
       OR ref_unit IS NULL
       OR gwp_total_a1a3 IS NULL
       OR gwp_biogenic_a1a3 IS NULL
       OR gwp_control IS NULL
    
    UNION ALL
    
    SELECT
        'eco_epd_gwp_control_within_tolerance' AS test_name,
        COUNT(*)::integer AS failed_rows,
        'GWP kontrollväärtus peab olema 0 või jääma 2% piiresse kogumõjust.' AS message
    FROM mart.eco_epd
    INNER JOIN latest_run AS r
      ON e.run_id = r.run_id
    WHERE gwp_control <> 0
    WHERE gwp_total_a1a3 IS NOT NULL
      AND gwp_control <> 0
      AND ABS(gwp_control) > GREATEST(ABS(gwp_total_a1a3) * 0.02, 0.0001)

    UNION ALL
  
    SELECT
        'eco_epd_biogenic_not_negative' AS test_name,
        COUNT(*)::integer AS failed_rows,
        'Biogeenne GWP ei tohi olla negatiivne.' AS message
    FROM mart.eco_epd
    INNER JOIN latest_run AS r
        ON e.run_id = r.run_id
    WHERE gwp_biogenic_a1a3 < 0

)
INSERT INTO quality.test_results (
    test_name,
    status,
    failed_rows,
    message
)
SELECT
    test_name,
    CASE WHEN failed_rows = 0 THEN 'passed' ELSE 'failed' END AS status,
    failed_rows,
    message
FROM test_cases
ORDER BY test_name;
