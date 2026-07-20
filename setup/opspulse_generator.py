"""OpsPulse synthetic dataset generator.

Generates the running case-study dataset for *AI-Based Data Engineering*
(Richie Bachala, Packt). One canonical definition, two load targets:

    Tier A (zero account):  local DuckDB file        --target duckdb
    Tier B (free trial):    Snowflake tables          --target snowflake
    SQL only:               emit portable INSERTs      --target sql

The generator is deterministic (fixed seed + fixed AS_OF date) and reproduces
the book's canonical facts:

  * Four *divergent* "active customer" definitions across teams:
        Sales ops ............ 14,230
        Customer success ..... 11,502
        Product analytics ....  9,847
        Finance ..............  8,319
  * The IoT data-quality quirk: ~4% NULL telemetry timestamps.

The whole point of OpsPulse is that four teams count "active customers" four
different ways against the *same* data. This script builds the data so those
four numbers fall out of four honest SQL definitions (see setup/sql/definitions.sql).

Usage
-----
    pip install -r setup/requirements-setup.txt

    # Tier A — local DuckDB (no account, no keys)
    python setup/opspulse_generator.py --target duckdb --out setup/opspulse.duckdb

    # Tier B — load into Snowflake (reads .env credentials)
    python setup/opspulse_generator.py --target snowflake

    # Just verify the divergence math without writing anything
    python setup/opspulse_generator.py --target none
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Canonical constants — do not change without updating the book / definitions. #
# --------------------------------------------------------------------------- #

SEED = 42
AS_OF = dt.date(2026, 6, 30)          # fixed "today" so counts are reproducible
N_CUSTOMERS = 20_000

# Window boundaries derived from AS_OF (kept as literals so the SQL in
# definitions.sql is portable across DuckDB and Snowflake).
WINDOW_90D = dt.date(2026, 4, 1)      # order within last ~90 days
WINDOW_30D = dt.date(2026, 6, 1)      # event within last ~30 days

# Divergent "active customer" definitions expressed as contiguous customer_id
# blocks. Each block has an EXACT size equal to the canonical team count, and
# the blocks overlap (as real divergence does). customer_id is 1-indexed.
#                       (first_id, last_id)  -> size
SALES_OPS_IDS = (1, 14_230)            # order in 90d                -> 14,230
FINANCE_IDS = (500, 8_818)             # PAID order in 90d           ->  8,319  (subset of sales)
PRODUCT_IDS = (3_000, 12_846)          # telemetry event in 30d      ->  9,847
CUST_SUCCESS_IDS = (2_000, 13_501)     # support ticket in 30d       -> 11,502

EXPECTED = {
    "sales_ops": 14_230,
    "customer_success": 11_502,
    "product_analytics": 9_847,
    "finance": 8_319,
}

IOT_NULL_TIMESTAMP_RATE = 0.04         # the canonical data-quality quirk

REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
INDUSTRIES = ["Manufacturing", "Logistics", "Retail", "Energy", "Healthcare"]
DEVICE_MODELS = ["OP-Sensor-100", "OP-Sensor-200", "OP-Gateway-X", "OP-Edge-Lite"]
WAREHOUSES = ["WH-EAST", "WH-WEST", "WH-EU", "WH-APAC"]


def _ids(block: tuple[int, int]) -> np.ndarray:
    """Inclusive customer_id range as an int array."""
    first, last = block
    return np.arange(first, last + 1, dtype=np.int64)


def _rand_dates(rng, start: dt.date, end: dt.date, n: int) -> list[dt.date]:
    span = (end - start).days
    offsets = rng.integers(0, span + 1, size=n)
    return [start + dt.timedelta(days=int(o)) for o in offsets]


# --------------------------------------------------------------------------- #
# Domain builders                                                             #
# --------------------------------------------------------------------------- #

def build_customers(rng) -> pd.DataFrame:
    ids = np.arange(1, N_CUSTOMERS + 1)
    return pd.DataFrame(
        {
            "customer_id": ids,
            "customer_name": [f"OpsPulse Customer {i:05d}" for i in ids],
            "region": rng.choice(REGIONS, size=N_CUSTOMERS),
            "segment": rng.choice(SEGMENTS, size=N_CUSTOMERS, p=[0.2, 0.35, 0.45]),
            "created_at": _rand_dates(rng, dt.date(2022, 1, 1), dt.date(2025, 12, 31), N_CUSTOMERS),
        }
    )


def build_orders(rng) -> pd.DataFrame:
    """ERP orders. Definitions that fall out of this table:

      * sales_ops = distinct customers with ANY order in last 90 days
      * finance   = distinct customers with a status='PAID' order in last 90 days
    """
    rows = []
    order_id = 1

    sales_ids = set(_ids(SALES_OPS_IDS).tolist())
    finance_ids = set(_ids(FINANCE_IDS).tolist())

    for cid in range(1, N_CUSTOMERS + 1):
        # Historical orders (older than 90d) for a broad set — adds realism and
        # ensures the 90d window genuinely filters. These may be PAID but are
        # outside the finance window, so they never inflate the counts.
        for _ in range(int(rng.integers(0, 3))):
            odate = _rand_dates(rng, dt.date(2024, 7, 1), dt.date(2026, 3, 31), 1)[0]
            rows.append((order_id, cid, odate, rng.choice(["PAID", "REFUNDED", "CANCELLED"]),
                         round(float(rng.uniform(50, 4000)), 2)))
            order_id += 1

        if cid in sales_ids:
            n_recent = int(rng.integers(1, 4))
            for k in range(n_recent):
                odate = _rand_dates(rng, WINDOW_90D, AS_OF, 1)[0]
                if cid in finance_ids and k == 0:
                    status = "PAID"          # guarantees finance qualification
                    amount = round(float(rng.uniform(100, 5000)), 2)
                else:
                    # Non-finance recent orders are deliberately NOT 'PAID' so the
                    # finance definition resolves to exactly the finance block.
                    status = rng.choice(["PENDING", "SHIPPED", "CANCELLED"])
                    amount = round(float(rng.uniform(50, 5000)), 2)
                rows.append((order_id, cid, odate, status, amount))
                order_id += 1

    df = pd.DataFrame(rows, columns=["order_id", "customer_id", "order_date", "status", "amount"])
    return df


def build_inventory(rng) -> pd.DataFrame:
    n = 1_200
    return pd.DataFrame(
        {
            "product_id": np.arange(1, n + 1),
            "warehouse": rng.choice(WAREHOUSES, size=n),
            "on_hand": rng.integers(0, 5000, size=n),
            "reorder_point": rng.integers(50, 800, size=n),
            "unit_cost": np.round(rng.uniform(5, 500, size=n), 2),
        }
    )


def build_devices(rng) -> pd.DataFrame:
    """One or more IoT devices per product-analytics customer, plus some others."""
    product_ids = _ids(PRODUCT_IDS)
    # extra devices for a random set of non-product customers (churned / offline)
    extra = rng.choice(np.arange(1, N_CUSTOMERS + 1), size=3_000, replace=False)
    owners = np.concatenate([product_ids, extra])
    n = len(owners)
    return pd.DataFrame(
        {
            "device_id": np.arange(1, n + 1),
            "customer_id": owners,
            "model": rng.choice(DEVICE_MODELS, size=n),
            "install_date": _rand_dates(rng, dt.date(2023, 1, 1), dt.date(2026, 5, 1), n),
        }
    )


def build_telemetry(rng, devices: pd.DataFrame) -> pd.DataFrame:
    """IoT telemetry. Definition that falls out of this table:

      * product_analytics = distinct customers with a NON-NULL telemetry
        timestamp in the last 30 days.

    Injects the canonical ~4% NULL-timestamp quirk WITHOUT disturbing the count:
    every product-analytics customer gets one guaranteed, protected, non-null
    recent event; nulls are only drawn from the extra event pool.
    """
    product_ids = set(_ids(PRODUCT_IDS).tolist())
    dev_by_cust = devices.groupby("customer_id")["device_id"].first().to_dict()

    rows = []          # (device_id, customer_id, metric, value, ts, _protected)

    # 1) Guaranteed recent event for each product-analytics customer.
    for cid in sorted(product_ids):
        did = dev_by_cust[cid]
        ts = _rand_dates(rng, WINDOW_30D, AS_OF, 1)[0]
        rows.append((did, cid, "temperature_c", round(float(rng.uniform(10, 90)), 2),
                     dt.datetime.combine(ts, dt.time(int(rng.integers(0, 24)))), True))

    # 2) Extra event pool across all devices. These are dated strictly BEFORE the
    #    30-day window so they never add new customers to the product-analytics
    #    count — only the guaranteed events above are "recent". This keeps the
    #    divergence count exact while still supplying rows for the NULL quirk.
    n_extra = 60_000
    dev_sample = devices.sample(n=n_extra, replace=True, random_state=SEED)
    for did, cid in zip(dev_sample["device_id"], dev_sample["customer_id"]):
        ts_date = _rand_dates(rng, dt.date(2026, 1, 1), dt.date(2026, 5, 31), 1)[0]
        ts = dt.datetime.combine(ts_date, dt.time(int(rng.integers(0, 24))))
        rows.append((int(did), int(cid), "temperature_c",
                     round(float(rng.uniform(10, 90)), 2), ts, False))

    df = pd.DataFrame(rows, columns=["device_id", "customer_id", "metric", "value",
                                     "event_timestamp", "_protected"])

    # Inject ~4% NULL timestamps, drawing only from the unprotected pool.
    target_nulls = int(round(IOT_NULL_TIMESTAMP_RATE * len(df)))
    pool = df.index[~df["_protected"]].to_numpy()
    null_idx = rng.choice(pool, size=min(target_nulls, len(pool)), replace=False)
    df.loc[null_idx, "event_timestamp"] = pd.NaT

    df = df.drop(columns="_protected").reset_index(drop=True)
    df.insert(0, "event_id", np.arange(1, len(df) + 1))
    return df


def build_support(rng) -> pd.DataFrame:
    """Support tickets. Definition that falls out of this table:

      * customer_success = distinct customers with a ticket created in last 30d.
    """
    cs_ids = _ids(CUST_SUCCESS_IDS)
    rows = []
    tid = 1
    for cid in cs_ids:
        created = _rand_dates(rng, WINDOW_30D, AS_OF, 1)[0]
        rows.append((tid, int(cid), created,
                     rng.choice(["LOW", "MEDIUM", "HIGH", "URGENT"]),
                     rng.choice(["OPEN", "PENDING", "RESOLVED"]),
                     rng.choice(["email", "chat", "phone"])))
        tid += 1
    # older tickets for a broad set (outside the 30d window)
    others = rng.choice(np.arange(1, N_CUSTOMERS + 1), size=4_000, replace=False)
    for cid in others:
        created = _rand_dates(rng, dt.date(2025, 6, 1), dt.date(2026, 5, 31), 1)[0]
        rows.append((tid, int(cid), created,
                     rng.choice(["LOW", "MEDIUM", "HIGH"]),
                     rng.choice(["RESOLVED", "CLOSED"]),
                     rng.choice(["email", "chat", "phone"])))
        tid += 1
    return pd.DataFrame(rows, columns=["ticket_id", "customer_id", "created_at",
                                       "priority", "status", "channel"])


def build_crm(rng, customers: pd.DataFrame) -> pd.DataFrame:
    n = len(customers)
    return pd.DataFrame(
        {
            "account_id": np.arange(1, n + 1),
            "customer_id": customers["customer_id"].to_numpy(),
            "industry": rng.choice(INDUSTRIES, size=n),
            "tier": rng.choice(["Gold", "Silver", "Bronze"], size=n, p=[0.15, 0.35, 0.5]),
            "account_owner": rng.choice([f"rep_{i:02d}" for i in range(1, 41)], size=n),
        }
    )


# --------------------------------------------------------------------------- #
# Verification — assert the four divergent counts before we load anything.     #
# --------------------------------------------------------------------------- #

def verify(orders: pd.DataFrame, telemetry: pd.DataFrame, support: pd.DataFrame) -> dict:
    recent_orders = orders[orders["order_date"] >= WINDOW_90D]
    sales_ops = recent_orders["customer_id"].nunique()
    finance = recent_orders[recent_orders["status"] == "PAID"]["customer_id"].nunique()

    tel = telemetry.dropna(subset=["event_timestamp"])
    tel_recent = tel[pd.to_datetime(tel["event_timestamp"]).dt.date >= WINDOW_30D]
    product = tel_recent["customer_id"].nunique()

    tickets_recent = support[support["created_at"] >= WINDOW_30D]
    customer_success = tickets_recent["customer_id"].nunique()

    got = {
        "sales_ops": int(sales_ops),
        "customer_success": int(customer_success),
        "product_analytics": int(product),
        "finance": int(finance),
    }
    null_rate = float(telemetry["event_timestamp"].isna().mean())

    print("\nDivergent 'active customer' counts (expected -> got):")
    ok = True
    for k, exp in EXPECTED.items():
        mark = "OK " if got[k] == exp else "XX "
        if got[k] != exp:
            ok = False
        print(f"  {mark}{k:20s} {exp:>7,d} -> {got[k]:>7,d}")
    print(f"\nIoT NULL-timestamp rate: {null_rate:.2%} (target ~{IOT_NULL_TIMESTAMP_RATE:.0%})")

    if not ok:
        raise AssertionError("Divergence counts do not match canonical values — data drift.")
    return got


# --------------------------------------------------------------------------- #
# Writers                                                                     #
# --------------------------------------------------------------------------- #

def _tables(rng) -> dict[str, pd.DataFrame]:
    customers = build_customers(rng)
    orders = build_orders(rng)
    inventory = build_inventory(rng)
    devices = build_devices(rng)
    telemetry = build_telemetry(rng, devices)
    support = build_support(rng)
    crm = build_crm(rng, customers)

    verify(orders, telemetry, support)

    return {
        "ERP_CUSTOMERS": customers,
        "ERP_ORDERS": orders,
        "ERP_INVENTORY": inventory,
        "CRM_ACCOUNTS": crm,
        "IOT_DEVICES": devices,
        "IOT_TELEMETRY": telemetry,
        "SUPPORT_TICKETS": support,
    }


def _definitions_sql() -> str:
    path = Path(__file__).parent / "sql" / "definitions.sql"
    return path.read_text() if path.exists() else ""


def _split_statements(sql: str) -> list[str]:
    statements = []
    for chunk in sql.split(";"):
        # Drop full-line SQL comments so a leading comment does not swallow the
        # statement, then keep whatever executable SQL remains.
        code = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if code:
            statements.append(code)
    return statements


def write_duckdb(tables: dict[str, pd.DataFrame], out: str) -> None:
    import duckdb

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(out)
    for name, df in tables.items():
        con.register("_tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    for stmt in _split_statements(_definitions_sql()):
        con.execute(stmt)
    con.close()
    print(f"\nTier A ready: DuckDB written to {out}")
    print("  Try:  duckdb", out, "-c \"SELECT * FROM v_active_customer_divergence;\"")


def write_snowflake(tables: dict[str, pd.DataFrame]) -> None:
    import snowflake.connector
    from snowflake.connector.pandas_tools import write_pandas

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parents[1] / ".env")
    except Exception:
        pass

    database = os.getenv("SNOWFLAKE_DATABASE", "OPSPULSE")
    schema = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    )
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    cur.execute(f"USE DATABASE {database}")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    cur.execute(f"USE SCHEMA {database}.{schema}")

    for name, df in tables.items():
        write_pandas(conn, df, name, auto_create_table=True, overwrite=True,
                     database=database, schema=schema)
        print(f"  loaded {name:20s} {len(df):>8,d} rows")

    for stmt in _split_statements(_definitions_sql()):
        cur.execute(stmt)

    cur.close()
    conn.close()
    print(f"\nTier B ready: loaded into {database}.{schema}")
    print(f"  Try:  SELECT * FROM {database}.{schema}.V_ACTIVE_CUSTOMER_DIVERGENCE;")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the OpsPulse dataset.")
    ap.add_argument("--target", choices=["duckdb", "snowflake", "none"], default="duckdb",
                    help="Where to load the data. 'none' just verifies the divergence math.")
    ap.add_argument("--out", default="setup/opspulse.duckdb",
                    help="DuckDB output path (used when --target duckdb).")
    args = ap.parse_args()

    rng = np.random.default_rng(SEED)
    tables = _tables(rng)

    if args.target == "duckdb":
        write_duckdb(tables, args.out)
    elif args.target == "snowflake":
        write_snowflake(tables)
    else:
        print("\n--target none: verification only, nothing written.")


if __name__ == "__main__":
    main()
