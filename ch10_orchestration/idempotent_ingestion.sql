-- Chapter 10: Intelligent Orchestration — Routing and Remediation
-- Section: 10.4 Idempotent ingestion patterns
-- Book: AI-Based Data Engineering (Packt)
--
-- NOTE: Code snippets marked with ... are illustrative stubs from the book text.
-- Complete implementations are provided where the full code is shown.
--
-- Idempotency property: running the load N times produces the same result as running it once.
-- Required for safe retries — which is what the triage DAG triggers.


-- ============================================================
-- Pattern 1: MERGE-ON-LOAD (incremental updates)
-- Safe to re-run multiple times; only net-new changes are applied.
-- Equivalent to what's in Chapter 8 document_extraction.sql — repeated here
-- in the orchestration context because idempotency enables safe retries.
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
ON  target.device_id        = source.device_id
AND target.calibration_date = source.calibration_date
AND target.calibration_type = source.calibration_type
WHEN MATCHED AND (
    target.offset_mm <> source.offset_mm
    OR target.passed  <> source.passed
) THEN UPDATE SET
    target.offset_mm   = source.offset_mm,
    target.passed      = source.passed,
    target.ingested_at = source.ingested_at
WHEN NOT MATCHED THEN INSERT (
    device_id, calibration_date, calibration_type,
    offset_mm, technician_id, facility_code,
    passed, notes, source_file, ingested_at
) VALUES (
    source.device_id, source.calibration_date, source.calibration_type,
    source.offset_mm, source.technician_id, source.facility_code,
    source.passed, source.notes, source.source_file, source.ingested_at
);


-- ============================================================
-- Pattern 2: Backfill safety check before manual load
-- Prevents double-loading a date range that already has data.
-- ============================================================
DECLARE
    existing_rows INT;
BEGIN
    SELECT COUNT(*) INTO :existing_rows
    FROM raw.device_calibration
    WHERE calibration_date BETWEEN '2025-03-01' AND '2025-03-31';

    IF (:existing_rows > 0) THEN
        RAISE EXCEPTION 'Backfill safety check failed: % rows already exist for this date range. '
            'Use MERGE-ON-LOAD pattern or manually clear the range first.'
            USING (existing_rows);
    END IF;

    -- Safe to load
    INSERT INTO raw.device_calibration
    SELECT * FROM @opspu_calibration_stage/calibration_2025_03_backfill/;
END;


-- ============================================================
-- Pattern 3: Row count baseline validation
-- Check that row count is within expected range before promoting
-- the load to the next stage.
-- ============================================================
SELECT
    CASE
        WHEN COUNT(*) < 1000 THEN 'FAIL: Row count below minimum threshold (1000)'
        WHEN COUNT(*) > 1000000 THEN 'FAIL: Row count above maximum threshold (1M)'
        ELSE 'PASS: ' || COUNT(*) || ' rows loaded'
    END AS validation_result,
    COUNT(*) AS row_count
FROM raw.device_calibration
WHERE ingested_at > DATEADD('hour', -1, CURRENT_TIMESTAMP());


-- ============================================================
-- Pattern 4: Approval gate — set Airflow variable from SQL
-- The triage DAG's ApprovalSensor polls this variable.
-- ============================================================
-- To approve a pending pipeline action:
-- To approve via Airflow CLI: airflow variables set approval_gate_opspu_calibration approved
--
-- To reject (triggers the PAUSE_FOR_REVIEW path):
-- To reject via Airflow CLI:  airflow variables set approval_gate_opspu_calibration rejected
--
-- In Airflow CLI:
-- airflow variables set approval_gate_opspu_calibration approved
