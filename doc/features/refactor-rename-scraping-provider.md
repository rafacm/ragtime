# Refactor: Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_*

## Problem

The scraping provider used generic `RAGTIME_LLM_*` env vars and a `get_llm_provider()` factory function, while all other providers followed the `RAGTIME_<PURPOSE>_*` naming convention (`SUMMARIZATION`, `EXTRACTION`, `TRANSCRIPTION`). This inconsistency made it unclear that the "LLM" provider was specifically the scraping provider, and broke the pattern developers rely on when adding or configuring providers.

## Changes

- **`ragtime/settings.py`** — Renamed `RAGTIME_LLM_PROVIDER` → `RAGTIME_SCRAPING_PROVIDER`, `RAGTIME_LLM_API_KEY` → `RAGTIME_SCRAPING_API_KEY`, `RAGTIME_LLM_MODEL` → `RAGTIME_SCRAPING_MODEL`.
- **`episodes/providers/factory.py`** — Renamed `get_llm_provider()` → `get_scraping_provider()`, updated all internal settings references and error messages.
- **`episodes/scraper.py`** — Updated import and call site to use `get_scraping_provider`.
- **`episodes/tests/test_scraper.py`** — Updated `@override_settings` to use `RAGTIME_SCRAPING_*` and all `@patch` decorators to reference `get_scraping_provider`.
- **`README.md`** — Updated env var documentation and Features & Fixes table entry.

## Verification

```bash
uv run python manage.py test episodes
```

All 68 tests pass.

## Files Modified

| File | Change |
|------|--------|
| `ragtime/settings.py` | Renamed 3 env var settings from `RAGTIME_LLM_*` to `RAGTIME_SCRAPING_*` |
| `episodes/providers/factory.py` | Renamed `get_llm_provider()` → `get_scraping_provider()`, updated settings refs and error messages |
| `episodes/scraper.py` | Updated import and call site |
| `episodes/tests/test_scraper.py` | Updated `@override_settings` and 4 `@patch` decorators |
| `README.md` | Updated env var docs and features table |
