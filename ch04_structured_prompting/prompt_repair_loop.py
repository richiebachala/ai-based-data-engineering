# Chapter 4: Prompting On-Ramp and Structured Prompting
# Section: 4.3 Repair loop — recover from insufficient_context fallback
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Prompt repair loop: the PTCF fallback instruction causes the model to
return {"error": "insufficient_context", "missing": "..."} instead of
guessing when context is inadequate.

The repair loop:
  1. Attempts generation with the initial prompt
  2. If the model signals insufficient_context, fetches the missing context
  3. Retries with the enriched context
  4. Returns an error after max_retries if context cannot be satisfied

This converts silent failures (plausible but wrong output) into explicit,
actionable signals.
"""

import anthropic
import json
from typing import Optional, Callable
from dataclasses import dataclass

client = anthropic.Anthropic()


@dataclass
class RepairResult:
    output:         str
    attempts:       int
    success:        bool
    error:          Optional[str] = None
    missing_context: Optional[str] = None


def _is_insufficient_context(response_text: str) -> tuple[bool, str]:
    """
    Check whether the model returned an insufficient_context signal.
    Returns (True, missing_description) if so, (False, "") otherwise.
    """
    try:
        parsed = json.loads(response_text)
        if parsed.get("error") == "insufficient_context":
            return True, parsed.get("missing", "unknown")
    except (json.JSONDecodeError, AttributeError):
        pass
    return False, ""


def attempt_generation(
    system_message: str,
    user_message: str,
    model: str = "claude-sonnet-4-5",
) -> str:
    """Single generation attempt. Returns the raw response text."""
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_message,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def prompt_repair_loop(
    system_message: str,
    user_message: str,
    context_fetcher: Callable[[str], str],
    max_retries: int = 2,
    model: str = "claude-sonnet-4-5",
) -> RepairResult:
    """
    Generation with repair loop.

    Args:
        system_message:  PTCF system message (includes fallback instruction)
        user_message:    PTCF user message (task + context + format)
        context_fetcher: Callable that takes a "missing" description string
                         and returns the additional context as a string.
                         This is where you'd call the catalog, lineage API, etc.
        max_retries:     Maximum number of repair attempts after initial failure
        model:           Model to use

    Returns:
        RepairResult with the final output and metadata
    """
    current_user_message = user_message

    for attempt in range(1, max_retries + 2):  # +2: 1 initial + max_retries repairs
        output = attempt_generation(system_message, current_user_message, model)

        is_insufficient, missing = _is_insufficient_context(output)

        if not is_insufficient:
            # Success: model produced output (may still need validation)
            return RepairResult(
                output=output,
                attempts=attempt,
                success=True,
            )

        if attempt > max_retries:
            # Exhausted retries
            return RepairResult(
                output="",
                attempts=attempt,
                success=False,
                error="max_retries_exceeded",
                missing_context=missing,
            )

        # Fetch the missing context and enrich the user message
        additional_context = context_fetcher(missing)
        current_user_message = (
            f"{user_message}\n\n"
            f"--- Additional context (fetched to address missing: {missing}) ---\n"
            f"{additional_context}"
        )

    # Should not reach here
    return RepairResult(output="", attempts=max_retries, success=False, error="unknown")


# --- Example context fetcher for OpsPulse ---

def opspu_context_fetcher(missing: str) -> str:
    """
    Example context fetcher: maps "missing" descriptions to OpsPulse context.
    In production, this calls the catalog MCP server or INFORMATION_SCHEMA.
    """
    # STUB: replace with real catalog / lineage API calls
    context_map = {
        "schema": "Table: FCT_ACTIVE_CUSTOMERS, Columns: customer_id, active_since, region_code",
        "definition": "active_customer: at least one qualifying event in trailing 30 days",
        "join condition": "FCT_ACTIVE_CUSTOMERS.customer_id = DIM_CUSTOMERS.customer_id",
    }
    for key, value in context_map.items():
        if key.lower() in missing.lower():
            return value
    return f"No additional context found for: {missing}"


if __name__ == "__main__":
    system = (
        "You are a senior Snowflake data engineer. Write read-only SELECT queries. "
        'If you cannot answer with the provided context, return: '
        '{"error": "insufficient_context", "missing": "<what is needed>"}'
    )
    user = (
        "Generate SQL to count active customers in EMEA for the last 30 days.\n"
        "Available tables: [NONE PROVIDED — intentionally incomplete]"
    )

    result = prompt_repair_loop(
        system_message=system,
        user_message=user,
        context_fetcher=opspu_context_fetcher,
        max_retries=2,
    )
    print(f"Success: {result.success}  Attempts: {result.attempts}")
    if result.success:
        print(f"Output: {result.output}")
    else:
        print(f"Error: {result.error}  Missing: {result.missing_context}")
