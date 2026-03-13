# Session: Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_*

**Date:** 2026-03-13

## Summary

Renamed the generic `RAGTIME_LLM_*` env vars and `get_llm_provider()` factory function to `RAGTIME_SCRAPING_*` / `get_scraping_provider()`, aligning the scraping provider with the `RAGTIME_<PURPOSE>_*` naming convention used by all other providers.

## Conversation

### Planning session

#### User

Asked to plan a rename of `RAGTIME_LLM_*` → `RAGTIME_SCRAPING_*` and `get_llm_provider` → `get_scraping_provider`.

#### Assistant

Explored the codebase to find all references to the old names across settings, factory, scraper, tests, and README. Produced a plan covering 5 files with specific line references for each change.

### Implementation session

#### User

Provided the plan and asked to implement it.

#### Assistant

Read all 5 files, applied the renames in parallel:
- `ragtime/settings.py` — renamed 3 env var settings
- `episodes/providers/factory.py` — renamed function, updated settings references and error messages
- `episodes/scraper.py` — updated import and call site
- `episodes/tests/test_scraper.py` — updated `@override_settings` and 4 `@patch` decorators
- `README.md` — updated env var documentation and added Features & Fixes entry

Ran `uv run python manage.py test episodes` — all 68 tests passed. Created branch, committed, pushed, and opened PR #21.
