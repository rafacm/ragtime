# Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_* — Plan

## Context

The `RAGTIME_LLM_*` env vars and `get_llm_provider()` are generic names for what is specifically the **scraping** LLM provider. Other providers already follow the `RAGTIME_<PURPOSE>_*` naming convention (SUMMARIZATION, EXTRACTION, TRANSCRIPTION). This refactor aligns the scraping provider with that convention.

## Changes

### 1. `ragtime/settings.py`

Rename settings:
- `RAGTIME_LLM_PROVIDER` → `RAGTIME_SCRAPING_PROVIDER`
- `RAGTIME_LLM_API_KEY` → `RAGTIME_SCRAPING_API_KEY`
- `RAGTIME_LLM_MODEL` → `RAGTIME_SCRAPING_MODEL`

### 2. `episodes/providers/factory.py`

- Rename `get_llm_provider()` → `get_scraping_provider()`
- Update settings references inside to `RAGTIME_SCRAPING_*`
- Update error message: `"RAGTIME_SCRAPING_API_KEY is not set"`

### 3. `episodes/scraper.py`

- Update import: `from .providers.factory import get_scraping_provider`
- Update call: `provider = get_scraping_provider()`

### 4. `episodes/tests/test_scraper.py`

- Update `@override_settings` to use `RAGTIME_SCRAPING_*`
- Update all `@patch("episodes.scraper.get_llm_provider")` → `@patch("episodes.scraper.get_scraping_provider")`

### 5. `README.md`

- Rename env vars in Configuration section
- Add `(default: openai)` to the provider line
- Add Features & Fixes table entry

## Files modified

| File | Action |
|------|--------|
| `ragtime/settings.py` | Edit — rename env var names |
| `episodes/providers/factory.py` | Edit — rename function and references |
| `episodes/scraper.py` | Edit — update import and call site |
| `episodes/tests/test_scraper.py` | Edit — update settings overrides and patches |
| `README.md` | Edit — update env var docs and features table |
