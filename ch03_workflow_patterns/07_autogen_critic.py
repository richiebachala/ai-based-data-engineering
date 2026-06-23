# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.2 Agent frameworks — AutoGen / AG2
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
AutoGen two-agent critique pattern for SQL review.

Use AutoGen/AG2 when:
  - The task maps to a generator + critic loop
  - The conversation structure is simple and bounded
  - You want model asymmetry (cheap generator, strong critic)

Bug fix vs book (C3-1): is_termination_msg must be on UserProxyAgent,
not on the AssistantAgent. This is the corrected implementation.
"""

try:
    import autogen
except ImportError:
    raise ImportError("pip install autogen-agentchat>=0.2")

import os

# --- Model configuration ---

LLM_CONFIG_GENERATOR = {
    "config_list": [{
        "model":   "claude-haiku-4-5",
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    }],
    "temperature": 0.7,
}

LLM_CONFIG_CRITIC = {
    "config_list": [{
        "model":   "claude-sonnet-4-5",
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    }],
    "temperature": 0.3,
}


def build_sql_review_agents(
    max_turns: int = 4,
) -> tuple["autogen.AssistantAgent", "autogen.UserProxyAgent"]:
    """
    Build a generator + critic pair for SQL review.

    Generator (haiku): produces the SQL
    Critic (sonnet):   reviews for correctness, safety, and style

    The critic approves by including the exact string APPROVED in its message.

    NOTE: is_termination_msg MUST be on UserProxyAgent (the human-proxy side),
    not on AssistantAgent. Setting it on AssistantAgent has no effect in AG2.
    """
    sql_generator = autogen.AssistantAgent(
        name="SQLGenerator",
        system_message=(
            "You are a senior Snowflake data engineer. "
            "When asked to write a SQL query, produce a clean, commented "
            "read-only SELECT. Use Snowflake syntax. No DML."
        ),
        llm_config=LLM_CONFIG_GENERATOR,
    )

    # is_termination_msg on the UserProxyAgent (critic role here)
    # terminates the conversation when the critic says APPROVED
    sql_critic = autogen.UserProxyAgent(
        name="SQLCritic",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=max_turns,
        is_termination_msg=lambda msg: "APPROVED" in msg.get("content", ""),
        system_message=(
            "You are a data quality critic reviewing Snowflake SQL. "
            "Check for: correctness, referential integrity, null handling, "
            "and safety (no DML, no cross-database joins, LIMIT present). "
            "If all checks pass, write APPROVED. "
            "If not, specify the exact problem and ask for a revision."
        ),
        llm_config=LLM_CONFIG_CRITIC,
        code_execution_config=False,
    )

    return sql_generator, sql_critic


def review_sql_with_agents(
    business_question: str,
    table_schema: str,
    max_turns: int = 4,
) -> str:
    """
    Run the generator-critic loop for a SQL review task.

    Returns the final approved SQL (or best attempt if max_turns reached).
    """
    generator, critic = build_sql_review_agents(max_turns=max_turns)

    # Initiate conversation: critic asks generator to produce the SQL
    critic.initiate_chat(
        generator,
        message=(
            f"Write a Snowflake SELECT query for this business question:\n"
            f"{business_question}\n\n"
            f"Table schema:\n{table_schema}\n\n"
            "Use CURRENT_DATE for date references. Add LIMIT 10000 unless aggregating."
        ),
    )

    # Extract the last generator message as the final SQL
    history = critic.chat_messages.get(generator, [])
    final_messages = [m for m in history if m.get("role") == "assistant"]
    return final_messages[-1]["content"] if final_messages else ""


if __name__ == "__main__":
    schema = """
    OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS
    Columns: customer_id VARCHAR, active_since TIMESTAMP_NTZ, region_code VARCHAR
    """
    question = "How many active customers are in the EMEA region as of today?"

    print(f"Reviewing SQL for: {question}")
    result = review_sql_with_agents(question, schema, max_turns=3)
    print(f"\nFinal SQL:\n{result}")
