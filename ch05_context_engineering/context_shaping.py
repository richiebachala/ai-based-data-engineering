# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Section: 5.3 Context shaping — assembly, budget, deduplication
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Context shaping: assemble retrieved chunks into a prompt-ready block
within a token budget, with semantic deduplication.

The context pipeline:
  1. Retrieve (BM25 + semantic + RRF)
  2. Deduplicate (semantic similarity; drop near-duplicates)
  3. Prioritize (sort by: authority tier → freshness → RRF score)
  4. Assemble (fit into token budget; track dropped sources)
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssembledContext:
    primary:       str           # always-in-context artifacts (pinned)
    supplementary: list          # retrieved + prioritized chunks
    tokens_used:   int
    tokens_budget: int
    dropped_sources: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Format the assembled context for injection into the prompt."""
        parts = []
        if self.primary:
            parts.append(f"--- Platform context (always present) ---\n{self.primary}")
        if self.supplementary:
            sup_text = "\n\n".join(
                f"[{c.source_type.upper()} | {c.source}]\n{c.content}"
                for c in self.supplementary
            )
            parts.append(f"--- Retrieved context ---\n{sup_text}")
        if self.dropped_sources:
            parts.append(
                f"--- Note: {len(self.dropped_sources)} source(s) excluded "
                f"due to token budget ---"
            )
        return "\n\n".join(parts)


# Token budget constants for OpsPulse components
COMPONENT_BUDGETS = {
    "sql_generation_tier1":    2_000,
    "sql_generation_tier2":    4_000,
    "sql_generation_tier3":    8_000,
    "column_description":      3_000,
    "anomaly_triage":          5_000,
    "lineage_impact":          8_000,
}

AUTHORITY_ORDER = {
    "schema":      1,
    "dbt_model":   2,
    "runbook":     3,
    "incident":    4,
    "policy":      5,
    "sample_data": 6,
}


def _is_near_duplicate(
    chunk_a_content: str,
    chunk_b_content: str,
    threshold: float = 0.85,
) -> bool:
    """
    Simple character-level Jaccard similarity for deduplication.
    In production: use embedding cosine similarity for semantic dedup.
    """
    words_a = set(chunk_a_content.lower().split())
    words_b = set(chunk_b_content.lower().split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) >= threshold


def deduplicate_chunks(chunks: list) -> list:
    """
    Remove near-duplicate chunks. Keep the first occurrence.
    Compares each chunk against all previously kept chunks.
    """
    kept = []
    for chunk in chunks:
        if not any(_is_near_duplicate(chunk.content, k.content) for k in kept):
            kept.append(chunk)
    return kept


def prioritize_chunks(chunks: list) -> list:
    """
    Sort chunks by:
    1. Authority tier (schema > dbt_model > runbook > incident > policy > sample)
    2. RRF score (higher is better) within each tier
    """
    return sorted(
        chunks,
        key=lambda c: (
            AUTHORITY_ORDER.get(getattr(c, 'source_type', ''), 99),
            -(getattr(c, 'rrf_score', 0.0)),
        )
    )


def assemble_context(
    pinned_artifacts: str,
    retrieved_chunks: list,
    token_budget: int,
    pinned_token_estimate: int = 0,
) -> AssembledContext:
    """
    Assemble context into a token-bounded block.

    Strategy:
      1. Always include pinned artifacts (capability index, glossary)
      2. Deduplicate retrieved chunks
      3. Prioritize by authority + RRF score
      4. Fill budget greedily; track dropped sources
    """
    deduped    = deduplicate_chunks(retrieved_chunks)
    prioritized = prioritize_chunks(deduped)

    tokens_used = pinned_token_estimate
    included    = []
    dropped     = []

    for chunk in prioritized:
        chunk_tokens = getattr(chunk, 'token_estimate', len(chunk.content) // 4)
        if tokens_used + chunk_tokens <= token_budget:
            included.append(chunk)
            tokens_used += chunk_tokens
        else:
            dropped.append(getattr(chunk, 'source', 'unknown'))

    return AssembledContext(
        primary=pinned_artifacts,
        supplementary=included,
        tokens_used=tokens_used,
        tokens_budget=token_budget,
        dropped_sources=dropped,
    )


if __name__ == "__main__":
    # Demo assembly without real chunks
    class FakeChunk:
        def __init__(self, source, source_type, content, rrf_score=0.5):
            self.source = source
            self.source_type = source_type
            self.content = content
            self.rrf_score = rrf_score
            self.token_estimate = len(content) // 4

    chunks = [
        FakeChunk("FCT_ACTIVE_CUSTOMERS", "schema", "customer_id VARCHAR..." * 20),
        FakeChunk("fct_active_customers", "dbt_model", "Model: active customer fact..." * 10),
        FakeChunk("incident-001", "incident", "Null rate spike on 2025-03-01" * 5),
    ]

    ctx = assemble_context(
        pinned_artifacts="Platform: Snowflake | Dialect: Snowflake SQL",
        retrieved_chunks=chunks,
        token_budget=500,
        pinned_token_estimate=10,
    )
    print(f"Tokens used: {ctx.tokens_used}/{ctx.tokens_budget}")
    print(f"Included chunks: {len(ctx.supplementary)}")
    print(f"Dropped: {ctx.dropped_sources}")
