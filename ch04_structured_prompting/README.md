# Chapter 4: Prompting On-Ramp and Structured Prompting
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `data_engineering_prompt.py` | PTCF prompt builder + SQL generation + column documentation + anomaly triage prompts |
| `structured_outputs_anthropic.py` | Anthropic `tool_choice` structured outputs for SQL, classification, and column descriptions |
| `structured_outputs_openai.py` | OpenAI `response_format` / `.parse()` structured outputs + prompt caching |
| `prompt_repair_loop.py` | Repair loop: retry with enriched context when model signals `insufficient_context` |
| `promptfoo/eval.yaml` | PromptFoo regression test suite — run in CI with `promptfoo eval` |

## Key concepts

- **Three failure modes**: Ambiguity, no constraints, no format specification
- **PTCF structure**: Persona → Task → Context → Format (4-component prompt anatomy)
- **Structured outputs**: API-enforced JSON via `tool_choice` (Anthropic) or `response_format` (OpenAI)
- **Fallback instruction**: Model returns `{"error": "insufficient_context"}` instead of guessing
- **Prompt regression testing**: PromptFoo runs in CI; baseline JSON frozen per version

## PromptFoo setup

```bash
npm install -g promptfoo
cd ch04_structured_prompting/
promptfoo eval --config promptfoo/eval.yaml
promptfoo view   # open the results UI
```

## Prompt versioning pattern

```
prompts/
  sql_generation/
    v1/prompt.json   # archived baseline
    v2/prompt.json   # current production
promptfoo-baselines/
  2025-03-01-sql-v1.json   # frozen baseline results
  2025-03-15-sql-v2.json
```

Freeze eval results as baselines when promoting to production.
Future evals compare against frozen baseline to detect regressions.
