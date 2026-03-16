# Langfuse Observability — Planning Session

## Session ID
0f60528e-6b16-41a5-b9d0-13c277121673

## Summary
Planned the addition of optional Langfuse LLM observability integration, covering provider-level OpenAI client swap and step-level tracing decorators across the processing pipeline.

### User
Entered plan mode and requested a plan for adding observability to LLM calls across the ingestion pipeline, using Langfuse as the tracing solution.

### Assistant
Explored the codebase to understand the current provider architecture and pipeline structure. Read `episodes/providers/base.py`, `episodes/providers/factory.py`, `episodes/providers/openai.py`, `episodes/signals.py`, `episodes/models.py`, `ragtime/settings.py`, and the five pipeline step files (transcribe, summarize, chunk, extract, resolve).

Considered several approaches:
- **Manual span instrumentation** — too invasive, requires changes in every LLM call site
- **Middleware-only approach** — misses non-HTTP pipeline calls run via Django Q2
- **Two-layer approach (provider-level + step-level)** — chosen as the design

Key design decisions:
1. **Zero overhead when disabled** — all Langfuse imports are deferred; when `RAGTIME_LANGFUSE_ENABLED` is falsy, no Langfuse code runs and no import errors occur
2. **Provider-level tracing** — swap the OpenAI client class for Langfuse's instrumented `OpenAI` wrapper, giving automatic token/cost tracking on every LLM call
3. **Step-level tracing** — `@observe_step` decorator on each pipeline step function groups LLM calls into logical traces (transcribe, summarize, chunk, extract, resolve)
4. **Session ID = ProcessingRun.pk** — ties all traces for one episode ingestion together in the Langfuse dashboard
5. **Graceful ImportError fallback** — if `langfuse` package is not installed, `is_enabled()` returns `False` and decorators become no-ops
6. **Central module** — `episodes/observability.py` houses `is_enabled()`, `get_openai_client_class()`, and `observe_step()`, keeping Langfuse logic out of provider/step files

Planned 11 files to modify or create:
- `pyproject.toml` — add `langfuse[openai]` as optional dependency
- `ragtime/settings.py` — add `RAGTIME_LANGFUSE_*` settings
- `episodes/observability.py` — new central module
- `episodes/providers/openai.py` — use dynamic client class
- 5 pipeline step files — add `@observe_step` decorators
- `core/management/commands/configure.py` — add Langfuse to wizard
- `.env.sample` — add Langfuse env vars

### User
Accepted the plan.

### Assistant
Saved the plan to `doc/plans/langfuse-observability.md`.
