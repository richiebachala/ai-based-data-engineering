-- Chapter 12: Governance and Security for Context and Agents
-- Section: 12.2 Snowflake masking policies and row access policies
-- Book: AI-Based Data Engineering (Packt)
--
-- NOTE: Code snippets marked with ... are illustrative stubs from the book text.
-- Complete implementations are provided where the full code is shown.


-- ============================================================
-- 1. Dynamic data masking — PII columns
--    Respects the caller's role; AI agents run as ANALYST_READ
--    and receive masked values unless they have DATA_STEWARD_ROLE
-- ============================================================
CREATE OR REPLACE MASKING POLICY mask_pii_email
AS (email_value VARCHAR) RETURNS VARCHAR ->
  CASE
    WHEN CURRENT_ROLE() IN ('DATA_STEWARD_ROLE', 'SYSADMIN') THEN email_value
    WHEN CURRENT_ROLE() = 'ANALYST_READ' THEN
        CONCAT(LEFT(email_value, 2), '***@', SPLIT_PART(email_value, '@', 2))
    ELSE '***MASKED***'
  END;


-- ============================================================
-- 2. Masking policy for device IDs (quasi-identifier)
--    Consistent hashing so analysts can track devices without
--    exposing the raw ID to AI agents
-- ============================================================
CREATE OR REPLACE MASKING POLICY mask_device_id
AS (device_id VARCHAR) RETURNS VARCHAR ->
  CASE
    WHEN CURRENT_ROLE() IN ('DATA_STEWARD_ROLE', 'SYSADMIN', 'IOT_ENGINEER') THEN device_id
    ELSE SHA2(CONCAT(device_id, 'opspu_salt_2025'), 256)  -- consistent pseudonymization
  END;


-- ============================================================
-- 3. Tag-based masking — apply policy to all PII-tagged columns
--    without modifying individual table DDL
-- ============================================================
-- Step 1: Create the PII tag
CREATE TAG IF NOT EXISTS data_governance.pii_classification
    ALLOWED_VALUES 'direct', 'quasi', 'indirect', 'none';

-- Step 2: Create a conditional masking policy that reads the tag
CREATE OR REPLACE MASKING POLICY mask_by_pii_tag
AS (col_value VARCHAR) RETURNS VARCHAR ->
  CASE
    WHEN CURRENT_ROLE() IN ('DATA_STEWARD_ROLE', 'SYSADMIN') THEN col_value
    WHEN SYSTEM$GET_TAG(
        'data_governance.pii_classification',
        'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS.CUSTOMER_EMAIL',
        'column'
    ) IN ('direct', 'quasi') THEN SHA2(col_value, 256)
    ELSE col_value
  END;

-- Step 3: Attach the tag to a column (done once per PII column)
ALTER TABLE OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS
    MODIFY COLUMN customer_email
    SET TAG data_governance.pii_classification = 'direct';


-- ============================================================
-- 4. Row access policy — region-based data sovereignty
--    Limits EMEA agents to EMEA rows; blocks cross-region access
-- ============================================================
CREATE OR REPLACE ROW ACCESS POLICY rap_region_sovereignty
AS (region_code VARCHAR) RETURNS BOOLEAN ->
  CASE
    WHEN CURRENT_ROLE() IN ('GLOBAL_ANALYST', 'SYSADMIN') THEN TRUE
    WHEN CURRENT_ROLE() = 'EMEA_ANALYST' AND region_code = 'EMEA' THEN TRUE
    WHEN CURRENT_ROLE() = 'APAC_ANALYST' AND region_code = 'APAC' THEN TRUE
    WHEN CURRENT_ROLE() = 'AMER_ANALYST' AND region_code = 'AMER' THEN TRUE
    ELSE FALSE
  END;

ALTER TABLE OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS
    ADD ROW ACCESS POLICY data_governance.rap_region_sovereignty
    ON (region_code);


-- ============================================================
-- 5. Row access policy — block AI tools from unreviewed tables
--    Tables with data_stewardship_review_required='true' are blocked
--    until a qualified steward clears the flag (Chapter 12.6)
-- ============================================================
CREATE OR REPLACE ROW ACCESS POLICY rap_block_unreviewed_tables
AS (dummy_col VARCHAR) RETURNS BOOLEAN ->
  CASE
    WHEN CURRENT_ROLE() IN ('SYSADMIN', 'DATA_STEWARD_ROLE') THEN TRUE
    -- Block AI tools from tables flagged for stewardship review
    WHEN SYSTEM$GET_TAG(
        'data_governance.data_stewardship_review_required',
        CONCAT(CURRENT_DATABASE(), '.', CURRENT_SCHEMA(), '.', CURRENT_TABLE()),
        'table'
    ) = 'true' THEN FALSE
    ELSE TRUE
  END;
-- Note: CURRENT_TABLE() is available inside RAP bodies in Snowflake.
-- Attach this policy to any table that may require stewardship review:
-- ALTER TABLE raw.device_telemetry
--     ADD ROW ACCESS POLICY data_governance.rap_block_unreviewed_tables
--     ON (device_id);  -- pass any existing column as the dummy arg


-- ============================================================
-- 6. Stewardship queue DDL (supports Chapter 12.6 workflow)
-- ============================================================
CREATE OR REPLACE TABLE data_governance.stewardship_queue (
    proposal_id           VARCHAR        NOT NULL,
    table_fqn             VARCHAR        NOT NULL,
    proposed_at           TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    ai_classification     VARIANT        NOT NULL,   -- EnterpriseTableClassification JSON
    trigger_reason        VARCHAR        NOT NULL,
    dag_run_id            VARCHAR,
    assigned_steward      VARCHAR,
    status                VARCHAR        NOT NULL DEFAULT 'pending',
    -- 'pending' | 'in_review' | 'approved' | 'modified' | 'rejected' | 'deferred'
    decision              VARCHAR,
    final_classification  VARIANT,
    reviewer              VARCHAR,
    reviewed_at           TIMESTAMP_TZ,
    reviewer_notes        VARCHAR,
    PRIMARY KEY (proposal_id)
);

-- Cluster for efficient status polling by the Airflow stewardship DAG
ALTER TABLE data_governance.stewardship_queue
    CLUSTER BY (status, proposed_at);


-- ============================================================
-- 7. Classification governance record table
-- ============================================================
CREATE OR REPLACE TABLE data_governance.table_classifications (
    table_fqn            VARCHAR        NOT NULL,
    classification_json  VARIANT        NOT NULL,
    requires_review      BOOLEAN        NOT NULL DEFAULT FALSE,
    reviewed_by          VARCHAR,
    reviewed_at          TIMESTAMP_TZ,
    PRIMARY KEY (table_fqn)
);
