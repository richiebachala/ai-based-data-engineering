# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Section: 5.5 Prompt caching — Anthropic ephemeral cache
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Prompt caching for high-frequency pipelines.

Anthropic cache mechanics:
  - Mark stable prefix with cache_control: {"type": "ephemeral"}
  - Minimum cached prefix: 1,024 tokens
  - TTL: 5 minutes, resets on each cache hit
  - Cache write cost: 1.25× normal input (paid once per TTL window)
  - Cache read cost: 0.10× normal input (90% savings per hit)
  - Break-even: 2 total calls (cache profitable from the 2nd call onward)

Prompt ordering rule (required for cache hits):
  system prompt → retrieved documents → conversation history → current query
  Any modification to the cached prefix invalidates the entry.

OpsPulse cost example:
  Schema preamble: 4,000 tokens × 100 calls/day × $3.00/M
  Without cache: $1.26/day
  With cache:    $0.195/day (85% savings)
"""

import anthropic
from dataclasses import dataclass
from typing import Optional

client = anthropic.Anthropic()


# The schema preamble is the same for all SQL generation calls
# against this platform. Cache it to save ~4,000 tokens per call.
OPSPU_SCHEMA_PREAMBLE = """
You are a senior Snowflake data engineer working with the OpsPulse data platform.

AVAILABLE TABLES AND SCHEMAS:

-- opspu_iot_telemetry: Raw IoT sensor data from all deployed devices
device_id     VARCHAR  -- Unique device identifier. Joins to dim_devices.
event_time    TIMESTAMP_NTZ  -- Event UTC timestamp. ±30s tolerance for device clock drift.
event_type    VARCHAR  -- One of: heartbeat, anomaly, threshold_breach, config_update.
signal_value  FLOAT    -- Raw sensor reading. Units depend on device_class.
region_code   VARCHAR  -- ISO 3166-1 alpha-2 region where device is deployed.
is_anomaly    BOOLEAN  -- True when signal_value exceeds 2-sigma threshold for device class.
ingested_at   TIMESTAMP_NTZ  -- When record entered the platform. Set by Snowpipe.

-- fct_inventory_exposure: Inventory risk exposure by product and region
product_id        VARCHAR   -- FK to dim_product_hierarchy.product_id
region_code       VARCHAR   -- ISO 3166-1 alpha-2
exposure_amount   NUMBER    -- Monetary exposure in USD
snapshot_date     DATE      -- Daily snapshot; use MAX(snapshot_date) for current
threshold_pct     FLOAT     -- Warning threshold as % of total exposure

-- fct_active_customers: Active customer fact
customer_id   VARCHAR       -- Surrogate key. Joins to dim_customers.
active_since  TIMESTAMP_NTZ -- Earliest qualifying event in trailing 30-day window.
region_code   VARCHAR       -- ISO 3166-1 alpha-2

SQL RULES:
- Use CURRENT_DATE. Never GETDATE() or NOW().
- Date math: DATEADD('day', -N, CURRENT_DATE)
- Read-only SELECT only. No DML, DDL, or CALL.
- Add LIMIT 10000 unless using aggregation.
"""  # ~700 chars / ~175 tokens — in production, extend to 4,000+ tokens


@dataclass
class CachedSQLResult:
    sql_output:     str
    model:          str
    input_tokens:   int
    cached_tokens:  int
    output_tokens:  int
    cache_hit:      bool

    @property
    def savings_pct(self) -> float:
        if self.input_tokens == 0:
            return 0.0
        return self.cached_tokens / self.input_tokens * 100


def generate_sql_with_cached_schema(
    business_question: str,
    extra_instructions: Optional[str] = None,
) -> CachedSQLResult:
    """
    Generate SQL with the large schema preamble served from cache.

    The schema preamble is the same for all SQL generation calls.
    Caching it saves ~4,000 tokens per call at 90% of normal cost.

    Structure (required for cache hits):
      system[0]: schema preamble (cached, stable)
      system[1]: dialect instructions (short, not cached)
      user:      business question (dynamic, never cached)
    """
    system_blocks = [
        {
            "type": "text",
            "text": OPSPU_SCHEMA_PREAMBLE,
            "cache_control": {"type": "ephemeral"}  # cache this stable prefix
        },
        {
            "type": "text",
            "text": (
                "Write read-only SELECT queries in Snowflake SQL dialect. "
                "Reference only the tables listed above. No DML, DDL, or CALL."
            )
            # No cache_control here — short instruction, not worth a separate cache slot
        }
    ]
    if extra_instructions:
        system_blocks.append({
            "type": "text",
            "text": extra_instructions,
        })

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_blocks,
        messages=[{"role": "user", "content": (
            f"Business question: {business_question}\n\n"
            "Return JSON: {sql, explanation, confidence}"
        )}]
    )

    usage = response.usage
    cached_tokens = getattr(usage, "cache_read_input_tokens", 0)

    return CachedSQLResult(
        sql_output=response.content[0].text,
        model=response.model,
        input_tokens=usage.input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=usage.output_tokens,
        cache_hit=cached_tokens > 0,
    )


if __name__ == "__main__":
    questions = [
        "How many active customers are in the EMEA region today?",
        "Which products have inventory exposure above threshold this week?",
        "Count anomalous IoT events in APAC for the last 24 hours",
    ]

    print("Running 3 SQL generation calls (schema preamble cached after first call):\n")
    for i, q in enumerate(questions, 1):
        result = generate_sql_with_cached_schema(q)
        print(f"  Call {i}: cache_hit={result.cache_hit} "
              f"| input={result.input_tokens} "
              f"| cached={result.cached_tokens} "
              f"| savings={result.savings_pct:.0f}%")
    print("\nSubsequent calls to the same schema should show cache_hit=True.")
