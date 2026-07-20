# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.1 Five composable workflow patterns — Parallelization
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Parallelization: run multiple independent LLM calls concurrently with
asyncio.gather. Each sub-task receives its own bounded context window.

Two variants:
  A. Parallel sections — split a large task into N independent chunks;
     gather results; synthesize
  B. Voting — run the same task N times; select the most consistent
     answer (or escalate if there is no consensus)

OpsPulse use case:
  - Document all 60 columns of fct_inventory_exposure concurrently
  - Run the same impact-analysis prompt N times and vote on the result
"""

import asyncio
import anthropic
from pydantic import BaseModel, Field
import json

client = anthropic.Anthropic()


# ============================================================
# Variant A: Parallel sections (document all columns at once)
# ============================================================

async def _describe_column(
    table_name: str,
    column_name: str,
    data_type: str,
    sample_values: list | None = None,
) -> dict:
    """Async: generate one column description (no thread pool; runs in executor)."""
    loop = asyncio.get_running_loop()

    def _call():
        sample_str = ""
        if sample_values:
            sample_str = f"\nSample values: {sample_values[:5]}"
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            system=(
                "Write one-sentence column descriptions for a dbt catalog. "
                "Audience: business analysts. Under 150 chars."
            ),
            messages=[{"role": "user", "content": (
                f"Table: {table_name}  Column: {column_name} ({data_type})"
                f"{sample_str}\n\nWrite a one-sentence description."
            )}]
        )
        return response.content[0].text.strip()

    description = await loop.run_in_executor(None, _call)
    return {"column_name": column_name, "description": description}


async def document_table_parallel(
    table_name: str,
    columns: list[dict],
) -> list[dict]:
    """
    Generate descriptions for all columns concurrently.
    Each column gets its own bounded context window.
    """
    tasks = [
        _describe_column(
            table_name,
            col["column_name"],
            col["data_type"],
            col.get("sample_values"),
        )
        for col in columns
    ]
    return await asyncio.gather(*tasks)


# ============================================================
# Variant B: Voting (run same task N times, pick consensus)
# ============================================================

class ImpactAssessment(BaseModel):
    table:             str
    is_breaking:       bool
    affected_consumers: list[str]
    confidence:        float = Field(ge=0.0, le=1.0)


async def _single_impact_vote(
    table_fqn: str,
    proposed_change: str,
    downstream_consumers: list[str],
) -> ImpactAssessment:
    """One vote in the impact assessment ensemble."""
    loop = asyncio.get_running_loop()

    def _call():
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system="You are a data impact analyst. Assess whether a schema change breaks downstream consumers.",
            tools=[{
                "name": "assess",
                "description": "Return an impact assessment.",
                "input_schema": ImpactAssessment.model_json_schema(),
            }],
            tool_choice={"type": "tool", "name": "assess"},
            messages=[{"role": "user", "content": (
                f"Table: {table_fqn}\n"
                f"Proposed change: {proposed_change}\n"
                f"Downstream consumers: {json.dumps(downstream_consumers)}"
            )}]
        )
        tool_call = next(b for b in response.content if b.type == "tool_use")
        return ImpactAssessment(**tool_call.input)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call)


async def impact_assessment_with_voting(
    table_fqn: str,
    proposed_change: str,
    downstream_consumers: list[str],
    n_votes: int = 3,
) -> dict:
    """
    Run the impact assessment N times in parallel and return
    the majority answer with a consensus confidence score.

    If fewer than ceil(n_votes/2) agree, escalate to a human.
    """
    tasks = [
        _single_impact_vote(table_fqn, proposed_change, downstream_consumers)
        for _ in range(n_votes)
    ]
    votes = await asyncio.gather(*tasks)

    breaking_votes = sum(1 for v in votes if v.is_breaking)
    is_breaking = breaking_votes > n_votes // 2
    consensus_pct = max(breaking_votes, n_votes - breaking_votes) / n_votes

    # Aggregate affected consumers across all votes
    all_affected = set()
    for v in votes:
        all_affected.update(v.affected_consumers)

    return {
        "table_fqn":           table_fqn,
        "proposed_change":     proposed_change,
        "is_breaking":         is_breaking,
        "affected_consumers":  list(all_affected),
        "consensus_pct":       consensus_pct,
        "votes":               [v.model_dump() for v in votes],
        "escalate":            consensus_pct < 0.67,  # < 2/3 agreement → escalate
    }


if __name__ == "__main__":
    # Demo: document FCT_INVENTORY_EXPOSURE columns in parallel
    columns = [
        {"column_name": "product_id",       "data_type": "VARCHAR"},
        {"column_name": "region_code",       "data_type": "VARCHAR"},
        {"column_name": "exposure_amount",   "data_type": "NUMBER"},
        {"column_name": "snapshot_date",     "data_type": "DATE"},
        {"column_name": "threshold_pct",     "data_type": "FLOAT"},
    ]
    results = asyncio.run(document_table_parallel("fct_inventory_exposure", columns))
    print("Parallel column documentation:")
    for r in results:
        print(f"  {r['column_name']}: {r['description']}")
