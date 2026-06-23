# Chapter 11: Evals and AI Observability in Production
# Section: 11.2 OpenTelemetry tracing for AI pipelines
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
OpenTelemetry tracing for AI pipeline components.

Uses GenAI semantic conventions for standardized span attributes:
  gen_ai.system, gen_ai.request.model, gen_ai.usage.input_tokens,
  gen_ai.usage.output_tokens + custom OpsPulse attributes.

This makes traces portable across Langfuse, Braintrust, and any
OTLP-compatible backend.
"""

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except ImportError:
    raise ImportError("pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc")

import anthropic
import os
from datetime import datetime, timezone
from typing import Optional, Callable
from functools import wraps


# ============================================================
# Tracer setup
# ============================================================

def setup_ai_tracing(
    service_name: str,
    otlp_endpoint: str = None,
) -> trace.Tracer:
    """
    Configure OpenTelemetry tracing for AI pipeline components.
    Sends spans to Langfuse or any OTLP-compatible backend.
    """
    otlp_endpoint = otlp_endpoint or os.environ.get(
        "OTLP_ENDPOINT", "http://localhost:4317"
    )
    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


# Global tracer (initialized once at pipeline startup)
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> trace.Tracer:
    """Get or initialize the global tracer."""
    global _tracer
    if _tracer is None:
        _tracer = setup_ai_tracing("opspu.ai.pipeline")
    return _tracer


# ============================================================
# Traced LLM call wrapper
# ============================================================

def traced_llm_call(
    component: str,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 1024,
    extra_attributes: dict | None = None,
) -> tuple[str, dict]:
    """
    Execute an Anthropic LLM call with OpenTelemetry tracing.

    Returns (response_text, usage_dict) where usage_dict contains
    input_tokens, output_tokens, cache_read_tokens.

    Span attributes follow GenAI semantic conventions:
      gen_ai.system = "anthropic"
      gen_ai.request.model = model name
      gen_ai.usage.input_tokens = token count
      gen_ai.usage.output_tokens = token count
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"llm.{component}") as span:
        # GenAI semantic convention attributes
        span.set_attribute("gen_ai.system",             "anthropic")
        span.set_attribute("gen_ai.request.model",      model)
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        span.set_attribute("opspu.component",           component)
        span.set_attribute("opspu.timestamp",           datetime.now(timezone.utc).isoformat())

        if extra_attributes:
            for k, v in extra_attributes.items():
                span.set_attribute(k, str(v))

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )

            usage = response.usage
            cached = getattr(usage, "cache_read_input_tokens", 0)

            # Record token usage in span
            span.set_attribute("gen_ai.usage.input_tokens",  usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
            span.set_attribute("opspu.cache_read_tokens",    cached)

            return response.content[0].text, {
                "input_tokens":      usage.input_tokens,
                "output_tokens":     usage.output_tokens,
                "cache_read_tokens": cached,
                "model":             model,
                "component":         component,
            }

        except Exception as e:
            span.record_exception(e)
            span.set_attribute("gen_ai.error", str(e)[:200])
            raise


# ============================================================
# Pipeline-level tracing decorator
# ============================================================

def trace_pipeline_step(step_name: str):
    """
    Decorator that wraps a pipeline function in an OpenTelemetry span.

    Usage:
        @trace_pipeline_step("sql_generation")
        def generate_sql(requirement, schema):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(f"pipeline.{step_name}") as span:
                span.set_attribute("pipeline.step",  step_name)
                span.set_attribute("pipeline.start", datetime.now(timezone.utc).isoformat())
                try:
                    result = fn(*args, **kwargs)
                    span.set_attribute("pipeline.status", "success")
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("pipeline.status", "error")
                    span.set_attribute("pipeline.error",  str(e)[:200])
                    raise
        return wrapper
    return decorator


# ============================================================
# Usage record for cost tracking
# ============================================================

class UsageRecord:
    """Accumulate token usage records across a pipeline run."""

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self.records: list[dict] = []

    def record(self, usage: dict) -> None:
        self.records.append({**usage, "pipeline_id": self.pipeline_id})

    def total_tokens(self) -> dict:
        return {
            "input":      sum(r.get("input_tokens",      0) for r in self.records),
            "output":     sum(r.get("output_tokens",     0) for r in self.records),
            "cache_read": sum(r.get("cache_read_tokens", 0) for r in self.records),
            "calls":      len(self.records),
        }


if __name__ == "__main__":
    print("OpenTelemetry AI tracing setup:")
    print(f"  OTLP endpoint: {os.environ.get('OTLP_ENDPOINT', 'http://localhost:4317')}")
    print(f"  Langfuse host: {os.environ.get('LANGFUSE_HOST', 'not set')}")
    print("")
    print("To send traces to Langfuse, set:")
    print("  LANGFUSE_SECRET_KEY=<your-secret-key>")
    print("  LANGFUSE_PUBLIC_KEY=<your-public-key>")
    print("  LANGFUSE_HOST=https://cloud.langfuse.com")
    print("  OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel")
