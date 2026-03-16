# Plan: Optional Langfuse LLM Observability Integration

## Context

RAGtime makes LLM calls across 5 pipeline steps (scrape, transcribe, summarize, extract, resolve) but has no visibility into requests/responses, token usage, latency, or cost. Integrate Langfuse as an optional observability layer that traces all LLM calls grouped by ProcessingRun. Zero overhead when disabled.

## Approach

Two complementary instrumentation layers:

| Layer | Scope | Mechanism |
|-------|-------|-----------|
| **A — Provider-level** | All OpenAI API calls | Swap `openai.OpenAI` for `langfuse.openai.OpenAI` in `providers/openai.py` — auto-captures every request |
| **B — Step-level** | Pipeline step grouping | Wrap each pipeline step with a Langfuse `@observe()` decorator, grouped by `session_id = ProcessingRun.pk` |

## Key Design Decisions

- **Opt-in only** — all Langfuse imports are deferred inside `if is_enabled()` blocks; `ImportError` falls back gracefully.
- **Session grouping** — `ProcessingRun.pk` is used as the Langfuse session ID so all traces for one run are grouped together.
- **Context propagation** — a `propagate_attributes` context manager threads `session_id` and step metadata into nested spans.
- **Langfuse v4 API** — target `langfuse>=4,<5` as an optional dependency group.

## Files to Modify/Create

| # | File | Action | Summary |
|---|------|--------|---------|
| 1 | `pyproject.toml` | modify | Add optional dependency group: `langfuse>=4,<5` |
| 2 | `ragtime/settings.py` | modify | Read `RAGTIME_LANGFUSE_ENABLED`, `SECRET_KEY`, `PUBLIC_KEY`, `HOST` |
| 3 | `episodes/observability.py` | **new** | `is_enabled()`, `get_openai_client_class()`, `observe_step()` decorator |
| 4 | `episodes/providers/openai.py` | modify | Use dynamic client class from observability module |
| 5 | 5 pipeline step files | modify | Add `@observe_step` decorators |
| 6 | `episodes/_configure_helpers.py` | modify | Add Langfuse section to configure wizard |
| 7 | `.env.sample` | modify | Document new `RAGTIME_LANGFUSE_*` variables |
| 8 | `core/tests/test_configure.py` | modify | Update wizard tests for new Langfuse fields |
| 9 | `episodes/tests/test_observability.py` | **new** | Tests for observability module |
| 10 | `README.md` | modify | Add observability documentation section |
| 11 | `CHANGELOG.md` | modify | Add entry for Langfuse integration |

## Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `RAGTIME_LANGFUSE_ENABLED` | `false` | Master toggle — when false, no Langfuse code runs |
| `RAGTIME_LANGFUSE_SECRET_KEY` | (empty) | Langfuse project secret key |
| `RAGTIME_LANGFUSE_PUBLIC_KEY` | (empty) | Langfuse project public key |
| `RAGTIME_LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse server URL (self-hosted or cloud) |
