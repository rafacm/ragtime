# Feature: Optional Langfuse LLM Observability Integration

**Date:** 2026-03-16

## Problem

RAGtime makes LLM calls across 5 pipeline steps (scrape, transcribe, summarize, extract, resolve) but has no visibility into requests/responses, token usage, latency, or cost. Debugging slow or expensive steps requires manual logging, and there is no way to track LLM behavior over time across episodes.

## Changes

### Optional dependency

- Added `langfuse>=4,<5` as an optional dependency in the `observability` extras group
- Install with `uv sync --extra observability`; zero impact when not installed

### Observability module (`episodes/observability.py`)

New module with three functions:

- `is_enabled()` — checks `RAGTIME_LANGFUSE_ENABLED` setting and, when true, sets `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST` environment variables from Django settings so the Langfuse SDK can pick them up
- `get_openai_client_class()` — returns `langfuse.openai.OpenAI` when observability is enabled (wraps OpenAI client with automatic tracing), otherwise returns the standard `openai.OpenAI`
- `observe_step(name)` — decorator that wraps pipeline step functions with Langfuse's `@observe()` decorator and `propagate_attributes` context manager; no-op passthrough when disabled

### Provider changes

- Modified `episodes/providers/openai.py` to obtain its client class via `get_openai_client_class()` instead of importing `openai.OpenAI` directly, enabling automatic request/response tracing when Langfuse is active

### Pipeline step decoration

- Added `@observe_step()` decorator to 5 pipeline functions:
  - `scrape_episode` in `episodes/scraper.py`
  - `transcribe_episode` in `episodes/transcriber.py`
  - `summarize_episode` in `episodes/summarizer.py`
  - `extract_entities` in `episodes/extractor.py`
  - `resolve_entities` in `episodes/resolver.py`

### Configuration wizard

- Added Langfuse section to the configure wizard with 4 fields: enabled toggle, secret key, public key, and host URL

### Environment and documentation

- Added all 4 variables to `.env.sample` with descriptions
- Added LLM Observability section to `README.md`
- Added changelog entry

### Tests

- 11 new tests in `episodes/tests/test_observability.py` covering:
  - `is_enabled()` with various setting combinations
  - `get_openai_client_class()` return values with and without Langfuse
  - `observe_step()` decorator behavior in enabled/disabled states
  - Graceful handling when `langfuse` package is not installed

## Key Parameters

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `RAGTIME_LANGFUSE_ENABLED` | `false` | Opt-in to avoid any overhead or dependency when not needed |
| `RAGTIME_LANGFUSE_SECRET_KEY` | (none) | Server-side key for Langfuse API authentication |
| `RAGTIME_LANGFUSE_PUBLIC_KEY` | (none) | Client-side key for Langfuse API authentication |
| `RAGTIME_LANGFUSE_HOST` | `http://localhost:3000` | Default assumes local Langfuse instance via Docker |

## Verification

1. All tests pass: `uv run python manage.py test` (161 tests)
2. Configure wizard shows Langfuse fields: `uv run python manage.py configure --show`
3. System checks pass: `uv run python manage.py check`
4. With Langfuse disabled: zero overhead, no `langfuse` imports at runtime
5. With Langfuse enabled and running locally: traces appear at `http://localhost:3000`

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added `langfuse>=4,<5` in `[project.optional-dependencies.observability]` |
| `ragtime/settings.py` | 4 new `RAGTIME_LANGFUSE_*` settings |
| `episodes/observability.py` | New — central Langfuse helpers (`is_enabled`, `get_openai_client_class`, `observe_step`) |
| `episodes/providers/openai.py` | Dynamic client class via `get_openai_client_class()` |
| `episodes/scraper.py` | `@observe_step` decorator on `scrape_episode` |
| `episodes/transcriber.py` | `@observe_step` decorator on `transcribe_episode` |
| `episodes/summarizer.py` | `@observe_step` decorator on `summarize_episode` |
| `episodes/extractor.py` | `@observe_step` decorator on `extract_entities` |
| `episodes/resolver.py` | `@observe_step` decorator on `resolve_entities` |
| `core/management/commands/_configure_helpers.py` | Langfuse section in wizard |
| `.env.sample` | 4 new `RAGTIME_LANGFUSE_*` variable docs |
| `core/tests/test_configure.py` | Updated wizard tests for new Langfuse fields |
| `episodes/tests/test_observability.py` | New — 11 tests for observability module |
| `README.md` | LLM Observability section |
| `CHANGELOG.md` | Entry for Langfuse integration |
