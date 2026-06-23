-- Chapter 2: The Modern Stack — Data + AI + Control Plane
-- Section: 2.2 Open formats and interoperability: Iceberg, Horizon Catalog, and Unity Catalog
-- Book: AI-Based Data Engineering (Packt)
--
-- NOTE: Code snippets marked with ... are illustrative stubs from the book text.
-- Complete implementations are provided where the full code is shown.

-- ============================================================
-- 1. Snowflake-native Iceberg table governed by Horizon Catalog
--    Standard for tables consumed only through Snowflake
-- ============================================================
CREATE OR REPLACE ICEBERG TABLE opspu_fct_calibration (
    device_id       VARCHAR         COMMENT 'Unique device identifier. Joins to dim_devices.',
    event_time      TIMESTAMP_NTZ   COMMENT 'Event timestamp in UTC. ±30s tolerance due to device clock drift.',
    signal_value    FLOAT           COMMENT 'Raw sensor reading. Units depend on device_class.',
    is_anomaly      BOOLEAN         COMMENT 'True if signal_value exceeds 2-sigma threshold for device class.',
    ingested_at     TIMESTAMP_NTZ   COMMENT 'Timestamp when record entered the platform. Set by Snowpipe.'
)
    EXTERNAL_VOLUME = 'opspu_s3_vol'
    BASE_LOCATION   = 'calibration/'
    AUTO_REFRESH    = TRUE;


-- ============================================================
-- 2. Cross-engine Iceberg table registered in Open Catalog
--    (Apache Polaris) — readable by Databricks, Spark, Trino
-- ============================================================
CREATE OR REPLACE ICEBERG TABLE opspu_iot_telemetry (
    device_id       VARCHAR         COMMENT 'Unique device identifier. Joins to dim_devices.',
    event_time      TIMESTAMP_NTZ   COMMENT 'Event timestamp in UTC. ±30s tolerance due to device clock drift.',
    event_type      VARCHAR         COMMENT 'One of: heartbeat, anomaly, threshold_breach, config_update.',
    signal_value    FLOAT           COMMENT 'Raw sensor reading. Units depend on device_class.',
    region_code     VARCHAR         COMMENT 'ISO 3166-1 alpha-2 region where device is deployed.',
    is_anomaly      BOOLEAN         COMMENT 'True if signal_value exceeds 2-sigma threshold for device class.',
    ingested_at     TIMESTAMP_NTZ   COMMENT 'Timestamp when record entered the platform. Set by Snowpipe.'
)
    CATALOG         = 'polaris_prod'      -- Open Catalog integration name
    EXTERNAL_VOLUME = 'opspu_s3_vol'
    BASE_LOCATION   = 'iot_telemetry/'
    AUTO_REFRESH    = TRUE;


-- ============================================================
-- 3. Schema evolution: retrieve current columns for AI agent context
--    First call in the agent's tool chain before generating SQL
-- ============================================================
SELECT
    column_name,
    data_type,
    is_nullable,
    comment              AS column_description
FROM information_schema.columns
WHERE table_schema = 'RAW'
  AND table_name   = 'OPSPU_IOT_TELEMETRY'
ORDER BY ordinal_position;

-- For snapshot-level schema history on Iceberg tables (Snowflake 2024+):
-- SELECT * FROM opspu_iot_telemetry$SNAPSHOTS
-- WHERE committed_at > DATEADD(day, -7, CURRENT_TIMESTAMP());


-- ============================================================
-- 4. Time travel: query data as of a specific timestamp
--    Used by agents to reproduce exact operating context during debugging
-- ============================================================
SELECT
    device_id,
    event_time,
    signal_value,
    is_anomaly
FROM opspu_iot_telemetry
AT (TIMESTAMP => '2025-03-12 08:00:00'::TIMESTAMP_TZ)
WHERE region_code = 'EMEA'
LIMIT 100;


-- ============================================================
-- 5. Time travel by snapshot ID (reproducible ML training datasets)
--    Snapshot IDs are stable; use them instead of wall-clock timestamps
--    when exact reproducibility matters
-- ============================================================
SELECT COUNT(*), AVG(signal_value)
FROM opspu_iot_telemetry
AT (SNAPSHOT => 4561392989987334174);


-- ============================================================
-- 6. Programmatic catalog query
--    The first tool call in an AI agent's chain: retrieve full
--    schema context before generating SQL or proposing a change
-- ============================================================
SELECT
    column_name,
    data_type,
    is_nullable,
    comment              AS column_description,
    NULL                 AS owner,
    NULL                 AS pii_classification
FROM information_schema.columns
WHERE table_schema = 'MARTS'
  AND table_name   = 'FCT_INVENTORY_EXPOSURE'
ORDER BY ordinal_position;
