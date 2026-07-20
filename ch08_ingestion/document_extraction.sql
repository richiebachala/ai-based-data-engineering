-- Chapter 8: AI-Assisted Ingestion, Profiling, and Documentation
-- Section: 8.4 Unstructured sources — PARSE_DOCUMENT + CORTEX.COMPLETE
-- Book: AI-Based Data Engineering (Packt)
--
-- NOTE: Code snippets marked with ... are illustrative stubs from the book text.
-- Complete implementations are provided where the full code is shown.
--
-- Bug fix C8-1: PARSE_DOCUMENT requires 3 arguments
--   Correct:  SNOWFLAKE.CORTEX.PARSE_DOCUMENT(@stage, filename, {'mode': 'LAYOUT'})
--   Wrong:    SNOWFLAKE.CORTEX.PARSE_DOCUMENT(@stage, filename)  <- missing mode arg
--
-- Bug fix C8-2: ORDER BY column_position -> ORDER BY ORDER_ID
--   The column 'column_position' doesn't exist; use the actual column name.


-- ============================================================
-- 1. PARSE_DOCUMENT: extract text from PDF calibration reports
--    (Bug fix C8-1: mode argument is required)
-- ============================================================
SELECT
    relative_path                 AS file_name,
    -- Correct: PARSE_DOCUMENT requires 3 arguments
    SNOWFLAKE.CORTEX.PARSE_DOCUMENT(
        @opspu_calibration_stage,
        relative_path,
        {'mode': 'LAYOUT'}         -- required third argument
    )::VARIANT                    AS document_content
FROM DIRECTORY(@opspu_calibration_stage)
WHERE relative_path LIKE '%.pdf'
LIMIT 100;


-- ============================================================
-- 2. LLM extraction from firmware notification emails
--    Extract structured fields from free-text email bodies
-- ============================================================
SELECT
    notification_id,
    email_received_at,
    SNOWFLAKE.CORTEX.COMPLETE(
        'claude-3-5-haiku',
        CONCAT(
            'Parse this firmware notification email and return JSON with fields: ',
            'device_model (string), firmware_version (string, e.g. "v4.2.1"), ',
            'release_date (YYYY-MM-DD), ',
            'severity (one of: critical, major, minor, informational), ',
            'affected_device_ids (array of strings, empty array if broadcast). ',
            'Return only JSON, no explanation. Email: ',
            email_body
        )
    )::VARIANT                    AS parsed_firmware_update
FROM raw.firmware_notifications
WHERE email_body IS NOT NULL;    -- idempotency: only process rows with content


-- ============================================================
-- 3. INFER_SCHEMA: detect schema from staged CSV files
-- ============================================================
SELECT *
FROM TABLE(
    INFER_SCHEMA(
        LOCATION => '@opspu_calibration_stage/calibration_2025_03/',
        FILE_FORMAT => 'opspu_csv_format'
    )
)
ORDER BY ORDER_ID;               -- Bug fix C8-2: ORDER_ID is the correct column


-- ============================================================
-- 4. Load calibration CSV using inferred schema
-- ============================================================
CREATE OR REPLACE TABLE raw.device_calibration (
    device_id           VARCHAR,
    calibration_date    DATE,
    calibration_type    VARCHAR,
    offset_mm           FLOAT,
    technician_id       VARCHAR,
    facility_code       VARCHAR,
    passed              BOOLEAN,
    notes               VARCHAR,
    source_file         VARCHAR,
    ingested_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

COPY INTO raw.device_calibration (
    device_id, calibration_date, calibration_type,
    offset_mm, technician_id, facility_code,
    passed, notes, source_file
)
FROM (
    SELECT
        $1::VARCHAR,             -- device_id
        $2::DATE,                -- calibration_date
        $3::VARCHAR,             -- calibration_type
        $4::FLOAT,               -- offset_mm
        $5::VARCHAR,             -- technician_id
        $6::VARCHAR,             -- facility_code
        $7::BOOLEAN,             -- passed
        $8::VARCHAR,             -- notes
        METADATA$FILENAME::VARCHAR -- source_file
    FROM @opspu_calibration_stage/calibration_2025_03/
)
FILE_FORMAT = (FORMAT_NAME = 'opspu_csv_format')
ON_ERROR = 'CONTINUE';           -- log bad rows; don't abort the load


-- ============================================================
-- 5. MERGE-ON-LOAD for idempotent incremental ingestion
--    (also used in Chapter 10 orchestration patterns)
-- ============================================================
MERGE INTO raw.device_calibration AS target
USING (
    SELECT
        $1::VARCHAR          AS device_id,
        $2::DATE             AS calibration_date,
        $3::VARCHAR          AS calibration_type,
        $4::FLOAT            AS offset_mm,
        $5::VARCHAR          AS technician_id,
        $6::VARCHAR          AS facility_code,
        $7::BOOLEAN          AS passed,
        $8::VARCHAR          AS notes,
        METADATA$FILENAME::VARCHAR AS source_file,
        CURRENT_TIMESTAMP()  AS ingested_at
    FROM @opspu_calibration_stage/calibration_2025_03/
) AS source
ON target.device_id = source.device_id
    AND target.calibration_date = source.calibration_date
    AND target.calibration_type = source.calibration_type
-- Update existing rows when the offset or pass/fail result changes
WHEN MATCHED AND (
    target.offset_mm <> source.offset_mm
    OR target.passed  <> source.passed
) THEN UPDATE SET
    target.offset_mm   = source.offset_mm,
    target.passed      = source.passed,
    target.ingested_at = source.ingested_at
-- Insert new rows
WHEN NOT MATCHED THEN INSERT (
    device_id, calibration_date, calibration_type,
    offset_mm, technician_id, facility_code,
    passed, notes, source_file, ingested_at
) VALUES (
    source.device_id, source.calibration_date, source.calibration_type,
    source.offset_mm, source.technician_id, source.facility_code,
    source.passed, source.notes, source.source_file, source.ingested_at
);
