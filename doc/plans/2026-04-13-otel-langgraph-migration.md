# Migrate RAGtime to Agent-Native Architecture

**Date:** 2026-04-13

## Context

RAGtime's ingestion pipeline is currently a hard-coded 8-step linear workflow orchestrated via Django signals + Django Q2 async tasks. Observability is tightly coupled to Langfuse via custom decorators. Pydantic AI is used only for a recovery agent.

This plan covers the first two pillars of the agent-native migration:
1. **OpenTelemetry** — replace Langfuse-specific instrumentation with OTel SDK, enabling pluggable backends (Langfuse, Sentry, etc.)
2. **LangGraph** — replace signal-driven pipeline with a stateful graph that has autonomous step ordering/skipping, visualizable in LangGraph Studio

Scott (the top-level chat agent) will be implemented in a later phase, building on this foundation.

---

## Phase 1: OpenTelemetry Migration (Foundation)

Every subsequent phase needs instrumentation. Doing OTel first means all new code is instrumented from day one.

### Changes

| Action | File | Details |
|--------|------|---------|
| Create | `episodes/telemetry.py` | OTel `TracerProvider` setup, `@trace_step(name)` and `@trace_provider` decorators, configurable OTLP exporter |
| Modify | `episodes/providers/openai.py` | Replace `@observe_provider` with `@trace_provider`, remove Langfuse client wrapper (`get_openai_client_class`), use plain `openai.OpenAI` |
| Modify | `episodes/scraper.py`, `transcriber.py`, `summarizer.py`, `extractor.py`, `resolver.py` | Replace `@observe_step` with `@trace_step` |
| Modify | `episodes/agents/agent.py` | Remove Langfuse-specific context propagation, replace with OTel span context |
| Modify | `episodes/apps.py` | Import `setup` from `telemetry` instead of `observability` |
| Modify | `ragtime/settings.py` | Replace `RAGTIME_LANGFUSE_*` with `RAGTIME_OTEL_*` vars |
| Modify | `pyproject.toml` | Add `opentelemetry-api`, `opentelemetry-sdk`; add optional `otel` extras for OTLP exporter |
| Modify | `.env.sample` | Replace Langfuse vars with OTel vars |
| Modify | `core/management/commands/configure.py` | Update config wizard for OTel settings |
| Delete | `episodes/observability.py` | Fully replaced by `telemetry.py` |

### New env vars
```
RAGTIME_OTEL_ENABLED=false
RAGTIME_OTEL_EXPORTER=otlp          # otlp | console | none
RAGTIME_OTEL_ENDPOINT=http://localhost:4318
RAGTIME_OTEL_SERVICE_NAME=ragtime
RAGTIME_OTEL_HEADERS=               # for auth (e.g., Langfuse base64 keys)
```

### Removed env vars
```
RAGTIME_LANGFUSE_ENABLED
RAGTIME_LANGFUSE_SECRET_KEY
RAGTIME_LANGFUSE_PUBLIC_KEY
RAGTIME_LANGFUSE_HOST
```

### Verification
- Run pipeline with `RAGTIME_OTEL_EXPORTER=console` and verify spans appear in terminal
- Run with OTLP exporter pointed at Jaeger (`docker run jaegertracing/all-in-one`) and verify traces in Jaeger UI
- Run existing tests — all should pass with OTel disabled

---

## Phase 2: LangGraph Ingestion Pipeline

Replace signal-driven orchestration with a LangGraph `StateGraph`. The orchestrator agent has autonomy over step ordering/skipping.

### New files

```
episodes/graph/
    __init__.py
    state.py          # EpisodeState TypedDict (episode_id, status flags, error, recovery state)
    nodes.py          # Thin wrappers calling existing step core logic
    edges.py          # Conditional routing functions (skip steps, route to recovery)
    pipeline.py       # build_pipeline_graph() → compiled StateGraph
    recovery_node.py  # Wraps existing Pydantic AI recovery agent
    run.py            # run_pipeline(episode_id, resume_from) entry point
```

### Graph design

```
scrape → download → transcribe → summarize → chunk → extract → resolve → embed → END
  ↓         ↓           ↑ (skip if transcript exists)
recovery ←──┘
  ↓
retry step or escalate → END
```

- Each node wraps an existing step function (extract core logic into `*_core(episode)` functions)
- Conditional edges inspect `EpisodeState` flags to skip completed steps
- Recovery node calls existing `AgentStrategy.attempt()` from `episodes/agents/`
- `processing.py` helpers (`start_step`, `complete_step`, `fail_step`) still called by nodes for audit trail

### What gets removed
- `episodes/signals.py` — remove `queue_next_step` post_save handler (keep custom signals as extension points)
- Django Q2 `async_task()` calls from step functions
- `django-q2` dependency and `Q_CLUSTER` config

### Refactoring pattern (applied to each step file)
- Extract core logic: `scrape_episode(episode_id)` → `scrape_episode_core(episode) -> dict`
- Graph node calls `scrape_episode_core` directly
- Old entry point removed (no backward compat needed — graph is the new entry point)

### Verification
- Run the compiled graph with a test episode URL
- Verify step skipping: create an episode with existing transcript, confirm graph skips transcribe
- Verify recovery: trigger a scraping failure, confirm recovery node activates and retries
- All existing tests pass

---

## Phase 3: LangGraph Server + Studio

Configuration-only once Phase 2 is done.

### New files

| File | Purpose |
|------|---------|
| `langgraph.json` | Server config pointing to `episodes.graph.pipeline:build_pipeline_graph` |
| `episodes/graph/server.py` | Calls `django.setup()` before graph import (LangGraph nodes need Django ORM) |

### Running locally
```bash
uv run langgraph dev   # Starts server on localhost:8123 (requires: uv sync --extra studio)
# Open LangGraph Studio desktop app → connect to localhost:8123
```

### Verification
- `uv run langgraph dev` starts without errors
- Studio shows the ingestion graph with all nodes and edges
- Can trigger a pipeline run from Studio and watch execution step by step

---

## Dependency Changes (`pyproject.toml`)

| Action | Package | Phase |
|--------|---------|-------|
| Add | `opentelemetry-api>=1.20`, `opentelemetry-sdk>=1.20` | 1 |
| Add (optional) | `opentelemetry-exporter-otlp-proto-http>=1.20` | 1 |
| Add | `langgraph>=0.4` | 2 |
| Remove | `django-q2>=1.7,<2` | 2 |
| Make optional | `langfuse>=4,<5` (no longer imported by default) | 1 |

---

## What's Preserved

- **Provider ABCs** (`episodes/providers/base.py`) — unchanged
- **Provider factory** (`episodes/providers/factory.py`) — unchanged
- **Processing audit trail** (`processing.py`, `ProcessingRun`, `ProcessingStep` models) — nodes still call `start_step`/`complete_step`/`fail_step`
- **Pydantic AI recovery agent** (`episodes/agents/`) — called by graph recovery node
- **Django as web framework** — LangGraph server runs alongside Django
- **Step core logic** — refactored but not rewritten
