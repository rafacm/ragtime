# OpenTelemetry Telemetry

**Date:** 2026-04-15

## Problem

RAGtime's observability layer was tightly coupled to Langfuse — the only supported tracing backend. This made it impossible to use other trace visualization tools (Jaeger, console output) or to run multiple collectors simultaneously. The Langfuse SDK was also the only way to instrument OpenAI calls, via a monkey-patched client class.

## Changes

Replaced the Langfuse-specific `episodes/observability.py` with a new `episodes/telemetry.py` built on the OpenTelemetry SDK. OpenTelemetry is now a core dependency (not optional). Three collectors are supported and can be enabled simultaneously via `RAGTIME_OTEL_COLLECTORS`:

- **console** — prints spans to stdout via `ConsoleSpanExporter`
- **jaeger** — exports traces via OTLP HTTP to Jaeger (or any OTLP-compatible backend)
- **langfuse** — Langfuse v4's OTel-native `LangfuseSpanProcessor` registers on the shared `TracerProvider`

### Public API changes

| Old (`observability.py`) | New (`telemetry.py`) |
|---|---|
| `observe_step(name)` | `trace_step(name)` |
| `observe_provider(func)` | `trace_provider(func)` |
| `set_observation_input()` | `record_llm_input()` |
| `set_observation_output()` | `record_llm_output()` |
| `get_openai_client_class()` | Removed — `OpenAIInstrumentor().instrument()` patches globally |
| `is_enabled()` | `is_enabled()` — now checks `RAGTIME_OTEL_COLLECTORS` |
| *(new)* | `is_langfuse_enabled()` |
| *(new)* | `get_tracer(name)` |

### Recovery agent

- `_run_with_langfuse()` → `_run_with_tracing()` — creates OTel spans, optionally wraps with `langfuse.propagate_attributes()` when Langfuse collector is active
- `_flush_langfuse()` → `_flush_traces()` — calls `TracerProvider.force_flush()` (flushes all processors)
- Screenshots: OTel span events for all collectors, `LangfuseMedia` binary attachments guarded by `is_langfuse_enabled()`

## Key parameters

| Variable | Default | Purpose |
|---|---|---|
| `RAGTIME_OTEL_COLLECTORS` | `""` | Comma-separated: `console`, `jaeger`, `langfuse` |
| `RAGTIME_OTEL_SERVICE_NAME` | `ragtime` | OTel resource service name |
| `RAGTIME_OTEL_JAEGER_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint for Jaeger |
| `RAGTIME_LANGFUSE_SECRET_KEY` | `""` | Langfuse auth (kept from before) |
| `RAGTIME_LANGFUSE_PUBLIC_KEY` | `""` | Langfuse auth (kept from before) |
| `RAGTIME_LANGFUSE_HOST` | `http://localhost:3000` | Langfuse host (kept from before) |

`RAGTIME_LANGFUSE_ENABLED` was removed — Langfuse activation is now controlled by including `langfuse` in `RAGTIME_OTEL_COLLECTORS`.

## Verification

1. Set `RAGTIME_OTEL_COLLECTORS=console`, submit an episode, verify spans print to worker stdout
2. Set `RAGTIME_OTEL_COLLECTORS=jaeger`, run `docker run -d --name jaeger -p 4318:4318 -p 16686:16686 jaegertracing/all-in-one:latest`, submit episode, view traces at `http://localhost:16686`
3. Set `RAGTIME_OTEL_COLLECTORS=langfuse` + keys, verify traces in Langfuse dashboard with session grouping
4. Set `RAGTIME_OTEL_COLLECTORS=console,jaeger` — both receive traces
5. Empty `RAGTIME_OTEL_COLLECTORS` — zero overhead, pipeline works normally
6. `uv run python manage.py test` — all tests pass

## Files modified

| File | Change |
|---|---|
| `pyproject.toml` | OTel as core dep; `[langfuse]` extra replaces `[observability]` |
| `episodes/telemetry.py` | New OTel-based telemetry module |
| `episodes/observability.py` | Deleted |
| `episodes/apps.py` | Import `setup` from `telemetry` |
| `episodes/scraper.py` | `@trace_step` from `telemetry` |
| `episodes/transcriber.py` | Same |
| `episodes/summarizer.py` | Same |
| `episodes/extractor.py` | Same |
| `episodes/resolver.py` | Same |
| `episodes/providers/openai.py` | `from openai import OpenAI` directly; `@trace_provider`; `record_llm_*` |
| `episodes/agents/agent.py` | `_run_with_tracing`, `_flush_traces`, `is_langfuse_enabled` guards |
| `episodes/agents/tools.py` | `is_langfuse_enabled` guards on screenshot attachments |
| `ragtime/settings.py` | New `RAGTIME_OTEL_*` settings |
| `.env.sample` | Updated env var documentation |
| `core/management/commands/_configure_helpers.py` | "Telemetry" wizard section |
| `docker-compose.yml` | Reverted (Jaeger runs standalone via `docker run`) |
| `episodes/tests/test_telemetry.py` | New tests replacing `test_observability.py` |
| `episodes/tests/test_observability.py` | Deleted |
| `core/tests/test_configure.py` | Updated wizard mock sequences |
