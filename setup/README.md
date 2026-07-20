# Run this first — the OpsPulse dataset

Every chapter in *AI-Based Data Engineering* runs against **OpsPulse**, a fictional
global operational analytics platform (ERP + CRM + IoT + support tickets). This
folder builds that dataset once, deterministically, and reproduces the canonical
facts the book relies on.

There are **two runnability tiers**. Pick the one that matches how far you want to go.

## Tier A — zero account (local DuckDB)

No Snowflake account and no API keys required. This is the fastest way to explore
the data and run the pure-Python / analytics chapters.

```bash
pip install -r setup/requirements-setup.txt
python setup/opspulse_generator.py --target duckdb --out setup/opspulse.duckdb
```

Then poke at it:

```bash
duckdb setup/opspulse.duckdb -c "SELECT * FROM v_active_customer_divergence;"
```

## Tier B — Snowflake free trial

Loads the *same* dataset into Snowflake so the SQL / Cortex / dbt chapters
(Ch 8, 9, 12) run against real tables. Uses the credentials in your `.env`
(see the top-level [`code/README.md`](../README.md)).

```bash
pip install -r setup/requirements-setup.txt
python setup/opspulse_generator.py --target snowflake
```

By default this creates database `OPSPULSE`, schema `PUBLIC`. Override with
`SNOWFLAKE_DATABASE` / `SNOWFLAKE_SCHEMA` in your `.env`.

> **Cost note:** loading OpsPulse is a handful of small tables and fits
> comfortably inside the Snowflake free trial ($400 credits / 30 days). Loading
> uses an XS warehouse for a few seconds.

## What gets built

Raw tables (four source domains):

| Table | Domain | Notes |
|-------|--------|-------|
| `ERP_CUSTOMERS`   | ERP     | 20,000 customers |
| `ERP_ORDERS`      | ERP     | recent + historical orders, PAID/PENDING/… statuses |
| `ERP_INVENTORY`   | ERP     | product stock, reorder points, unit cost |
| `CRM_ACCOUNTS`    | CRM     | account tier, industry, owner |
| `IOT_DEVICES`     | IoT     | devices per customer |
| `IOT_TELEMETRY`   | IoT     | ~4% **NULL** `event_timestamp` (the canonical quirk) |
| `SUPPORT_TICKETS` | Support | tickets with priority / status / channel |

Views ([`sql/definitions.sql`](sql/definitions.sql)):

- `v_active_sales_ops`, `v_active_finance`, `v_active_product`,
  `v_active_customer_success` — the four **divergent** "active customer" definitions.
- `v_active_customer_divergence` — the side-by-side "aha" query from Chapter 1.
- `fct_active_customers` — the **reconciled** single definition.
- `fct_inventory_exposure`, `fct_device_reliability` — the other two canonical facts.

## The divergence, reproduced

The generator asserts the four canonical counts before it writes anything, so a
run that succeeds proves the data matches the book:

```
Divergent 'active customer' counts (expected -> got):
  OK sales_ops             14,230 ->  14,230
  OK customer_success      11,502 ->  11,502
  OK product_analytics      9,847 ->   9,847
  OK finance                8,319 ->   8,319

IoT NULL-timestamp rate: 4.00% (target ~4%)
```

Run `python setup/opspulse_generator.py --target none` to see this check without
writing any output.

## Determinism

Fixed random seed (`SEED = 42`) and a fixed reference date (`AS_OF = 2026-06-30`)
mean every run produces byte-identical data and the same canonical counts,
regardless of when you run it.

---

> **Status: scaffold.** This generator is a working first cut that reproduces the
> Chapter 1 divergence and the IoT quirk. The `fct_inventory_exposure` and
> `fct_device_reliability` facts, and richer CRM activity, will be fleshed out as
> the per-chapter examples are wired to the dataset (see WS2 in the launch plan).
