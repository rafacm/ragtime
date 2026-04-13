# Migrate to OpenTelemetry and LangGraph

**Date:** 2026-04-13

## Problem

The ingestion pipeline was tightly coupled to Langfuse for observability (custom decorators, Langfuse-specific client wrapping) and used Django Q2 signal-based dispatch for orchestration. This architecture:

- Locked observability to a single vendor (Langfuse)
- Made the pipeline a rigid linear chain with no step skipping or autonomous routing
- Required a separate Django Q2 worker process
- Could not be visualized or inspected via a UI

## Changes

### Phase 1: OpenTelemetry Migration

Replaced Langfuse-specific instrumentation with the OpenTelemetry SDK. Traces can now be exported to any OTLP-compatible backend (Langfuse, Sentry, Jaeger, etc.).

- Created `episodes/telemetry.py` — `TracerProvider` setup, `@trace_step(name)` and `@trace_provider` decorators, `record_llm_input/output` span event helpers, configurable OTLP exporter
- Updated all step files (`scraper.py`, `transcriber.py`, `summarizer.py`, `extractor.py`, `resolver.py`) to use `@trace_step` instead of `@observe_step`
- Updated `episodes/providers/openai.py` — use plain `openai.OpenAI` client, `@trace_provider` decorator, `record_llm_input/output` for span events
- Updated `episodes/agents/agent.py` — replaced Langfuse context propagation with OTel span context, `_flush_otel()` instead of `_flush_langfuse()`
- Updated `episodes/agents/tools.py` — replaced Langfuse screenshot media with OTel span events
- Deleted `episodes/observability.py` (256 lines) — fully replaced by `telemetry.py`

### Phase 2: LangGraph Ingestion Pipeline

Replaced Django signal-based dispatch and Django Q2 async tasks with a LangGraph `StateGraph`.

- Created `episodes/graph/` package:
  - `state.py` — `EpisodeState` TypedDict
  - `nodes.py` — thin wrappers calling existing step functions, refreshing state from DB
  - `edges.py` — `route_entry` (determines start step based on existing data), `after_step` (continue/recovery/end), `after_recovery` (retry/give up)
  - `pipeline.py` — `build_pipeline_graph()` compiles a 10-node StateGraph (route, scrape, download, transcribe, summarize, chunk, extract, resolve, embed, recovery)
  - `run.py` — `run_pipeline(episode_id)` entry point
- Added `handle_step_failure_from_graph()` to `episodes/recovery.py` for graph-initiated recovery
- Removed `queue_next_step` post_save signal handler from `episodes/signals.py`
- Removed signal-based recovery connection from `episodes/apps.py`
- Updated `episodes/admin.py` — replaced `async_task()` with `threading.Thread` + `run_pipeline()`
- Removed Django Q2 from `INSTALLED_APPS`, `Q_CLUSTER` config, and `pyproject.toml` dependencies

### Phase 3: LangGraph Studio

- Created `langgraph.json` — server config pointing to the pipeline graph
- Created `episodes/graph/server.py` — Django setup for LangGraph server (ensures `django.setup()` before graph import)

### Documentation & Configuration

- Updated `README.md`, `doc/README.md`, `CLAUDE.md` to reflect new architecture
- Updated `.env.sample` with `RAGTIME_OTEL_*` variables replacing `RAGTIME_LANGFUSE_*`
- Updated configure wizard (`_configure_helpers.py`) with OpenTelemetry fields
- Updated all test files (removed ~100 `async_task` patches, deleted `test_signals.py` and `test_observability.py`, created `test_telemetry.py`)

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_OTEL_EXPORTER` | `otlp` (default) | Standard OTLP HTTP exporter; `console` for debugging, `none` to disable |
| `RAGTIME_OTEL_ENDPOINT` | `http://localhost:4318` | Standard OTLP HTTP port |
| `RAGTIME_OTEL_SERVICE_NAME` | `ragtime` | Identifies traces in the backend |

## Verification

1. Run tests: `uv run python manage.py test` — all 211 tests pass
2. Console tracing: set `RAGTIME_OTEL_ENABLED=true` and `RAGTIME_OTEL_EXPORTER=console`, run pipeline, verify spans in terminal
3. Jaeger: `docker run -p 4318:4318 -p 16686:16686 jaegertracing/all-in-one`, run pipeline, view at `http://localhost:16686`
4. LangGraph Studio: `uv sync --extra studio && uv run langgraph dev`, open Studio desktop app, verify graph visualization
5. Django check: `uv run python manage.py check` — no issues

## Files Modified

| File | Change |
|------|--------|
| `episodes/telemetry.py` | **Created** — OTel TracerProvider, decorators, span event helpers |
| `episodes/graph/__init__.py` | **Created** — package init |
| `episodes/graph/state.py` | **Created** — EpisodeState TypedDict |
| `episodes/graph/nodes.py` | **Created** — graph nodes wrapping step functions |
| `episodes/graph/edges.py` | **Created** — conditional routing functions |
| `episodes/graph/pipeline.py` | **Created** — StateGraph definition and compilation |
| `episodes/graph/run.py` | **Created** — pipeline entry point |
| `episodes/graph/server.py` | **Created** — Django setup for LangGraph server |
| `episodes/tests/test_telemetry.py` | **Created** — OTel telemetry tests |
| `langgraph.json` | **Created** — LangGraph server config |
| `episodes/observability.py` | **Deleted** — replaced by telemetry.py |
| `episodes/tests/test_observability.py` | **Deleted** — replaced by test_telemetry.py |
| `episodes/tests/test_signals.py` | **Deleted** — signal dispatch tests no longer relevant |
| `episodes/providers/openai.py` | Replaced Langfuse wrappers with OTel decorators |
| `episodes/agents/agent.py` | Replaced Langfuse tracing with OTel spans |
| `episodes/agents/tools.py` | Replaced Langfuse media with OTel span events |
| `episodes/apps.py` | Import telemetry instead of observability, remove recovery signal |
| `episodes/signals.py` | Removed queue_next_step post_save handler |
| `episodes/recovery.py` | Added handle_step_failure_from_graph() |
| `episodes/admin.py` | Replaced async_task with threading + run_pipeline |
| `episodes/scraper.py` | @trace_step instead of @observe_step |
| `episodes/transcriber.py` | @trace_step instead of @observe_step |
| `episodes/summarizer.py` | @trace_step instead of @observe_step |
| `episodes/extractor.py` | @trace_step instead of @observe_step |
| `episodes/resolver.py` | @trace_step instead of @observe_step |
| `ragtime/settings.py` | Replaced RAGTIME_LANGFUSE_* with RAGTIME_OTEL_*, removed Q_CLUSTER |
| `pyproject.toml` | Added opentelemetry/langgraph, removed django-q2 |
| `.env.sample` | Replaced Langfuse vars with OTel vars |
| `core/management/commands/_configure_helpers.py` | Updated wizard for OTel fields |
| `README.md` | Updated architecture, tech stack, setup docs |
| `doc/README.md` | Updated pipeline, recovery, observability sections |
| `CLAUDE.md` | Updated architecture and tech choices |
| 13 test files | Removed async_task patches, updated for new architecture |
