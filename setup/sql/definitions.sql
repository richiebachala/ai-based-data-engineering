-- OpsPulse canonical definitions
-- =============================================================================
-- Portable SQL (runs on both DuckDB and Snowflake). Loaded automatically by
-- opspulse_generator.py after the raw tables are created.
--
-- The star of the OpsPulse story: FOUR teams count "active customers" FOUR
-- different ways against the SAME data. These views make that divergence
-- explicit — and reproduce the canonical numbers from Chapter 1 (Table 1-3):
--
--     Sales ops ............ 14,230   (any order in last 90 days)
--     Customer success ..... 11,502   (support ticket in last 30 days)
--     Product analytics ....  9,847   (telemetry event in last 30 days)
--     Finance ..............  8,319   (PAID order in last 90 days)
--
-- Window boundaries are literals derived from AS_OF = 2026-06-30 so the SQL is
-- engine-portable (no DATEADD / INTERVAL dialect differences).
-- =============================================================================

-- Sales ops: any order in the last ~90 days.
CREATE OR REPLACE VIEW v_active_sales_ops AS
SELECT DISTINCT customer_id
FROM erp_orders
WHERE order_date >= DATE '2026-04-01';

-- Finance: a revenue-recognized (PAID) order in the last ~90 days.
CREATE OR REPLACE VIEW v_active_finance AS
SELECT DISTINCT customer_id
FROM erp_orders
WHERE order_date >= DATE '2026-04-01'
  AND status = 'PAID';

-- Product analytics: a telemetry event with a NON-NULL timestamp in the last ~30 days.
-- (The ~4% NULL-timestamp rows are silently dropped here — the data-quality quirk
-- that makes this count diverge from the others.)
CREATE OR REPLACE VIEW v_active_product AS
SELECT DISTINCT customer_id
FROM iot_telemetry
WHERE event_timestamp IS NOT NULL
  AND CAST(event_timestamp AS DATE) >= DATE '2026-06-01';

-- Customer success: a support ticket created in the last ~30 days.
CREATE OR REPLACE VIEW v_active_customer_success AS
SELECT DISTINCT customer_id
FROM support_tickets
WHERE created_at >= DATE '2026-06-01';

-- Side-by-side divergence — this is the "aha" query from Chapter 1.
CREATE OR REPLACE VIEW v_active_customer_divergence AS
SELECT 'sales_ops'        AS definition, COUNT(*) AS active_customers FROM v_active_sales_ops
UNION ALL
SELECT 'customer_success' AS definition, COUNT(*) FROM v_active_customer_success
UNION ALL
SELECT 'product_analytics' AS definition, COUNT(*) FROM v_active_product
UNION ALL
SELECT 'finance'          AS definition, COUNT(*) FROM v_active_finance;

-- =============================================================================
-- Canonical facts (the single-source-of-truth the book advocates building).
-- =============================================================================

-- fct_active_customers: the RECONCILED definition — genuine economic OR product
-- engagement (a PAID order in 90d, or a live telemetry event in 30d). This is
-- the "one number" that replaces the four divergent ones.
CREATE OR REPLACE VIEW fct_active_customers AS
SELECT customer_id FROM v_active_finance
UNION
SELECT customer_id FROM v_active_product;

-- fct_inventory_exposure: capital tied up in inventory by warehouse, plus a
-- count of products sitting below their reorder point.
CREATE OR REPLACE VIEW fct_inventory_exposure AS
SELECT
    warehouse,
    ROUND(SUM(on_hand * unit_cost), 2)                              AS exposure_value,
    SUM(CASE WHEN on_hand < reorder_point THEN 1 ELSE 0 END)        AS products_below_reorder,
    COUNT(*)                                                        AS product_count
FROM erp_inventory
GROUP BY warehouse;

-- fct_device_reliability: per-model telemetry health, surfacing the NULL-timestamp
-- data-quality rate (the OpsPulse IoT quirk) as a first-class metric.
CREATE OR REPLACE VIEW fct_device_reliability AS
SELECT
    d.model,
    COUNT(*)                                                                       AS event_count,
    SUM(CASE WHEN t.event_timestamp IS NULL THEN 1 ELSE 0 END)                     AS null_timestamp_events,
    ROUND(AVG(CASE WHEN t.event_timestamp IS NULL THEN 1.0 ELSE 0.0 END), 4)       AS null_timestamp_rate,
    COUNT(DISTINCT d.device_id)                                                    AS device_count
FROM iot_telemetry t
JOIN iot_devices d ON d.device_id = t.device_id
GROUP BY d.model;
