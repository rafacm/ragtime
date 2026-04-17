# OpenTelemetry as Primary Telemetry Source

**Date:** 2026-04-15

## Context

RAGtime currently has a Langfuse-specific observability layer in `episodes/observability.py`. The goal is to make **OpenTelemetry the always-on telemetry backbone** with **console, Jaeger, and Langfuse as optional collectors**. Telemetry itself is not optional — what's optional is where traces get sent.

PR #88 (`feature/otel-langgraph-migration`) already prototyped this: it created `episodes/telemetry.py`, made OTel a core dependency, and deleted `observability.py`. We'll build on that design but diverge in key ways: support multiple simultaneous collectors (not just one exporter), preserve Langfuse-specific features (session_id, screenshots), and skip the LangGraph migration (separate effort).

---

## Step 1: Update dependencies (`pyproject.toml`)

OTel becomes a **core dependency** (not optional). Langfuse becomes an optional extra for those who want that collector.

```toml
dependencies = [
    # ... existing deps ...
    "opentelemetry-api>=1.29,<2",
    "opentelemetry-sdk>=1.29,<2",
    "opentelemetry-exporter-otlp-proto-http>=1.29,<2",
    "opentelemetry-instrumentation-openai>=0.59",
]

[project.optional-dependencies]
langfuse = ["langfuse>=4,<5"]
recovery = ["pydantic-ai>=1.30,<2", "playwright>=1.40,<2"]
```

- PR #88 used `opentelemetry-exporter-otlp-proto-http` (HTTP, port 4318) — we follow that choice. Jaeger supports both gRPC (4317) and HTTP (4318); HTTP is simpler (no grpc dependency).
- `ConsoleSpanExporter` ships with `opentelemetry-sdk`.
- The old `[observability]` extra is removed; replaced by `[langfuse]`.

## Step 2: Rename `observability.py` → `telemetry.py`

Delete `episodes/observability.py` (256 lines) and create `episodes/telemetry.py`.

### Public API (same shape, new names matching PR #88)

| Old (`observability.py`) | New (`telemetry.py`) | Change |
|---|---|---|
| `setup()` | `setup()` | Configures TracerProvider with multiple processors |
| `is_enabled()` | `is_enabled()` | Always True when any collector is configured (or console fallback) |
| `observe_step(name)` | `trace_step(name)` | Pure OTel spans with `tracer.start_as_current_span()` |
| `observe_provider(func)` | `trace_provider(func)` | Pure OTel child spans |
| `set_observation_input()` | `record_llm_input()` | OTel span events instead of Langfuse observation updates |
| `set_observation_output()` | `record_llm_output()` | OTel span events |
| `get_openai_client_class()` | *(removed)* | Replaced by `OpenAIInstrumentor().instrument()` |
| *(new)* | `is_langfuse_enabled()` | True when Langfuse collector is active |
| *(new)* | `get_tracer(name)` | Returns OTel tracer instance |

### New env var schema

| Variable | Default | Purpose |
|---|---|---|
| `RAGTIME_OTEL_COLLECTORS` | `""` | Comma-separated: `console`, `jaeger`, `langfuse`. Empty = no tracing. |
| `RAGTIME_OTEL_SERVICE_NAME` | `ragtime` | OTel resource service name |
| `RAGTIME_OTEL_JAEGER_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint for Jaeger |
| `RAGTIME_LANGFUSE_SECRET_KEY` | `""` | Langfuse auth (when `langfuse` in collectors) |
| `RAGTIME_LANGFUSE_PUBLIC_KEY` | `""` | Langfuse auth |
| `RAGTIME_LANGFUSE_HOST` | `http://localhost:3000` | Langfuse host |

### `setup()` — TracerProvider with multiple processors

```
1. Create TracerProvider with Resource(service.name)
2. For each collector in RAGTIME_OTEL_COLLECTORS:
   - console → SimpleSpanProcessor(ConsoleSpanExporter())
   - jaeger  → BatchSpanProcessor(OTLPSpanExporter(endpoint=jaeger_endpoint))
   - langfuse → set LANGFUSE_* env vars, call langfuse.get_client()
                 (Langfuse v4 auto-registers its SpanProcessor on the active TracerProvider)
3. trace.set_tracer_provider(provider)
4. If langfuse in collectors: langfuse.get_client() (registers after provider is set)
5. OpenAIInstrumentor().instrument()
```

### `trace_step(name)` — Langfuse attribute propagation

PR #88 uses plain `ragtime.*` span attributes. For Langfuse compatibility, we also need to call `langfuse.propagate_attributes()` when the Langfuse collector is active (Langfuse reads `session_id`, `user_id`, `metadata` from this, not from span attributes alone):

```python
with tracer.start_as_current_span(name, attributes=attributes):
    if is_langfuse_enabled():
        from langfuse import propagate_attributes
        with propagate_attributes(session_id=session_id, user_id=user_id, metadata=metadata):
            return func(episode_id, *args, **kwargs)
    else:
        return func(episode_id, *args, **kwargs)
```

### `record_llm_input()` / `record_llm_output()` — span events

Follow PR #88's approach: use `span.add_event("llm.input", attributes={...})` and `span.add_event("llm.output", attributes={...})` instead of Langfuse observation updates.

## Step 3: Update all call sites

Every file that imports from `episodes.observability` needs updating:

| File | Changes |
|---|---|
| `episodes/scraper.py` | `@observe_step` → `@trace_step`, import from `telemetry` |
| `episodes/transcriber.py` | Same |
| `episodes/summarizer.py` | Same |
| `episodes/extractor.py` | Same |
| `episodes/resolver.py` | Same |
| `episodes/providers/openai.py` | Remove `get_openai_client_class()`, use `from openai import OpenAI` directly. `@observe_provider` → `@trace_provider`. `set_observation_input` → `record_llm_input`. `set_observation_output` → `record_llm_output`. |
| `episodes/apps.py` | `from .telemetry import setup as setup_telemetry` |
| `episodes/agents/agent.py` | `_run_with_langfuse` → `_run_with_tracing`, `_flush_langfuse` → `_flush_traces`, guard Langfuse-specific code with `is_langfuse_enabled()` |
| `episodes/agents/tools.py` | Guard `langfuse.get_client().update_current_span()` with `is_langfuse_enabled()` |

## Step 4: Update recovery agent (`episodes/agents/agent.py`)

- **Context isolation**: `attach(OTelContext())` / `detach` stays — already pure OTel
- **`_run_with_tracing()`**: Create OTel span for recovery, optionally wrap with `propagate_attributes()` when Langfuse active
- **`_attach_screenshots()`**: Add OTel span events for all collectors (metadata); keep `LangfuseMedia` guarded by `is_langfuse_enabled()`
- **`_flush_traces()`**: Call `trace.get_tracer_provider().force_flush()` instead of `langfuse.flush()`
- **`instrument=True`**: Keep on Agent — Pydantic AI OTel instrumentation works with any TracerProvider

## Step 5: Update settings and configuration

### `ragtime/settings.py`
Replace Langfuse settings block (lines 221-225) with:
```python
# Telemetry (OpenTelemetry)
RAGTIME_OTEL_COLLECTORS = os.getenv('RAGTIME_OTEL_COLLECTORS', '')
RAGTIME_OTEL_SERVICE_NAME = os.getenv('RAGTIME_OTEL_SERVICE_NAME', 'ragtime')
RAGTIME_OTEL_JAEGER_ENDPOINT = os.getenv('RAGTIME_OTEL_JAEGER_ENDPOINT', 'http://localhost:4318')

# Langfuse collector settings
RAGTIME_LANGFUSE_SECRET_KEY = os.getenv('RAGTIME_LANGFUSE_SECRET_KEY', '')
RAGTIME_LANGFUSE_PUBLIC_KEY = os.getenv('RAGTIME_LANGFUSE_PUBLIC_KEY', '')
RAGTIME_LANGFUSE_HOST = os.getenv('RAGTIME_LANGFUSE_HOST', 'http://localhost:3000')
```

### `.env.sample`
Replace lines 65-73 with new env vars (see table above).

### `core/management/commands/_configure_helpers.py`
Replace "LLM Observability" system (lines 127-143) with "Telemetry" containing two subsystems:
1. **OpenTelemetry** — `RAGTIME_OTEL_`: `COLLECTORS`, `SERVICE_NAME`, `JAEGER_ENDPOINT`
2. **Langfuse** — `RAGTIME_LANGFUSE_`: `SECRET_KEY`, `PUBLIC_KEY`, `HOST`

## Step 6: Add Jaeger to `docker-compose.yml`

Add `jaeger` service using `jaegertracing/jaeger:latest` (all-in-one):
- Port `4318` (OTLP HTTP)
- Port `16686` (Jaeger UI)

## Step 7: Update tests

### `episodes/tests/test_observability.py` → `episodes/tests/test_telemetry.py`

| Current test | Change |
|---|---|
| `IsEnabledTest` (6 tests) | Test `RAGTIME_OTEL_COLLECTORS` parsing; empty = disabled, `console` = enabled, etc. |
| `GetOpenaiClientClassTest` | **Delete** — function removed |
| `ObserveStepTest` | Rename to `TraceStepTest`, mock OTel tracer |
| `SetObservationInputTest` | Rename to `RecordLlmInputTest`, mock `trace.get_current_span()` |

**New tests:**
- `SetupTest` — verify TracerProvider gets correct processors per collector config
- `IsLangfuseEnabledTest` — True only when `langfuse` in collectors
- `TraceProviderTest` — verify child span creation
- `ConfiguredCollectorsTest` — comma-separated list parsing

### `core/tests/test_configure.py`
Update to match new wizard sections (same as PR #88 did).

## Step 8: Update documentation

- **`doc/README.md`**: Replace "LLM Observability (Langfuse)" section with "Telemetry (OpenTelemetry)" covering console, Jaeger, Langfuse collectors
- **`README.md`**: Move OpenTelemetry from "What's coming" to implemented features; keep LangGraph in "What's coming" as separate effort
- **Feature doc**: `doc/features/2026-04-15-opentelemetry-telemetry.md`
- **Plan doc**: `doc/plans/2026-04-15-opentelemetry-telemetry.md` (copy of this plan)
- **Session transcripts**: planning + implementation
- **`CHANGELOG.md`**: Entry under 2026-04-15
- **`CLAUDE.md`**: No changes needed (already references observability generically)

---

## Critical files to modify

| File | Summary |
|---|---|
| `pyproject.toml` | OTel as core dep, `[langfuse]` extra replaces `[observability]` |
| `episodes/observability.py` | **Delete** |
| `episodes/telemetry.py` | **Create** — OTel TracerProvider, multiple collectors, pure OTel decorators |
| `episodes/scraper.py` | `@trace_step`, import from `telemetry` |
| `episodes/transcriber.py` | Same |
| `episodes/summarizer.py` | Same |
| `episodes/extractor.py` | Same |
| `episodes/resolver.py` | Same |
| `episodes/providers/openai.py` | `from openai import OpenAI` directly, `@trace_provider`, `record_llm_*` |
| `episodes/apps.py` | Import `setup` from `telemetry` |
| `episodes/agents/agent.py` | Rename tracing functions, guard Langfuse-specific code |
| `episodes/agents/tools.py` | Guard Langfuse screenshot code |
| `ragtime/settings.py` | New `RAGTIME_OTEL_*` settings |
| `.env.sample` | New env vars |
| `core/management/commands/_configure_helpers.py` | "Telemetry" wizard section |
| `docker-compose.yml` | Add Jaeger service |
| `episodes/tests/test_telemetry.py` | **Create** (replaces `test_observability.py`) |
| `episodes/tests/test_observability.py` | **Delete** |
| `core/tests/test_configure.py` | Update for new wizard sections |

## Existing code to reuse

- `ProcessingRun` queries in `trace_step()` — session_id construction logic stays identical
- Recovery agent context isolation (`attach`/`detach` OTelContext) — already pure OTel
- `record_llm_input()` validation logic — same dual calling convention from PR #88
- Test structure from `test_observability.py` — adapt mocks from Langfuse to OTel

## Verification

1. **No collectors**: `RAGTIME_OTEL_COLLECTORS=""` — OTel no-op tracer, zero overhead, pipeline works normally
2. **Console**: `RAGTIME_OTEL_COLLECTORS=console` — spans print to Django Q2 worker stdout when processing an episode
3. **Jaeger**: `RAGTIME_OTEL_COLLECTORS=jaeger`, `docker compose up jaeger`, submit episode, open `http://localhost:16686`, find `ragtime` service traces with step spans
4. **Langfuse**: `RAGTIME_OTEL_COLLECTORS=langfuse` + API keys, submit episode, verify traces in Langfuse with session_id grouping
5. **Multiple**: `RAGTIME_OTEL_COLLECTORS=console,jaeger` — both receive traces simultaneously
6. **Tests**: `uv run python manage.py test episodes` + `uv run python manage.py test core` — all pass
7. **Recovery**: Trigger a scraping failure, verify recovery trace is independent (not nested under pipeline trace)
