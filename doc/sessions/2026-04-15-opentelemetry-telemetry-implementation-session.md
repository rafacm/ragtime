# OpenTelemetry Telemetry — Implementation Session

**Date:** 2026-04-15

**Session ID:** d2be50c4-9a66-4faf-bb43-29fbe4b0733a

## Summary

Implemented the migration from Langfuse-specific `episodes/observability.py` to OpenTelemetry-based `episodes/telemetry.py` with support for console, Jaeger, and Langfuse as optional collectors.

### User

Approved the plan after revisions.

### Assistant

Created branch `feature/opentelemetry-telemetry` from `main` and implemented the plan in sequence:

**1. Updated `pyproject.toml`** — Made `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and `opentelemetry-instrumentation-openai` core dependencies. Replaced `[observability]` extra with `[langfuse]` extra. Had to adjust `opentelemetry-instrumentation-openai` version constraint from `>=0.59` to `>=0.40` since only 0.57.0 was available in the lockfile's time window.

**2. Created `episodes/telemetry.py`** (320 lines) — New module with:
- `setup()`: Configures `TracerProvider` with one `SpanProcessor` per collector. Console uses `SimpleSpanProcessor(ConsoleSpanExporter())`, Jaeger uses `BatchSpanProcessor(OTLPSpanExporter())`, Langfuse auto-registers via `langfuse.get_client()` after `set_tracer_provider()`. Then calls `OpenAIInstrumentor().instrument()`.
- `is_enabled()`, `_configured_collectors()`, `is_langfuse_enabled()`, `get_tracer()`: Core utility functions.
- `trace_step(name)`: Pure OTel spans with optional `langfuse.propagate_attributes()` for session/user grouping.
- `trace_provider(func)`: OTel child spans for provider methods.
- `record_llm_input()` / `record_llm_output()`: Span events instead of Langfuse observation updates. Same dual calling convention (chat-style and dict-style).

**3. Updated 5 pipeline step files** — Changed imports and decorator names: `@observe_step` → `@trace_step`, from `telemetry` instead of `observability`.

**4. Updated `episodes/providers/openai.py`** — Removed `get_openai_client_class()`, using `from openai import OpenAI` directly. Switched decorators and recording functions.

**5. Updated recovery agent** (`episodes/agents/agent.py`, `episodes/agents/tools.py`):
- `_run_with_langfuse` → `_run_with_tracing`: Creates OTel span, optionally wraps with `propagate_attributes()` when Langfuse active.
- `_attach_screenshots`: OTel span events for all collectors + guarded `LangfuseMedia` for Langfuse.
- `_flush_langfuse` → `_flush_traces`: Uses `TracerProvider.force_flush()`.
- Screenshot attachments in `tools.py` guarded with `is_langfuse_enabled()`.

**6. Updated `episodes/apps.py`** — Import `setup` from `telemetry`.

**7. Updated configuration** — `ragtime/settings.py` (new `RAGTIME_OTEL_*` settings), `.env.sample`, `_configure_helpers.py` ("Telemetry" wizard section with OpenTelemetry and Langfuse subsystems).

**8. Added Jaeger to `docker-compose.yml`** — Under `telemetry` profile with OTLP HTTP (4318) and UI (16686) ports.

**9. Created `episodes/tests/test_telemetry.py`** (170 lines) — Tests for `_configured_collectors`, `is_enabled`, `is_langfuse_enabled`, `trace_step`, and `record_llm_input`. Deleted `test_observability.py`. Updated `core/tests/test_configure.py` mock sequences for the new wizard fields.

**10. Deleted `episodes/observability.py`**.

**11. Ran full test suite** — 232 tests pass (9 skipped for optional deps). Initial run had 2 failures in configure wizard tests due to changed field count; fixed by adding 2 extra mock input values for the new OTel fields.

**12. Updated documentation** — `doc/README.md` (replaced "LLM Observability (Langfuse)" section with "Telemetry (OpenTelemetry)"), `README.md` (moved OTel to implemented features, kept LangGraph in "What's coming"), created feature doc and plan doc, updated CHANGELOG.
