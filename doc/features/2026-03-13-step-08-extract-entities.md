# Step 8: Extract Entities

**Date:** 2026-03-13

## Problem

After summarization (Step 7), episodes transition to `EXTRACTING` status but nothing processes them. The pipeline needs LLM-based entity extraction to identify jazz entities (artists, bands, albums, venues, etc.) from transcripts. Extracted entities are stored as structured JSON for later deduplication and resolution. The extraction LLM must be independently configurable from the summarizer and scraper.

## Changes

- **Entity type definitions** (`episodes/entity_types.yaml`): New YAML file defining 15 entity types with explicit `key` (snake_case), `name`, `description`, and `examples`. Keys serve as JSON property names, avoiding runtime conversion of names like "Recording Session".

- **Shared language module** (`episodes/languages.py`): Extracted `ISO_639_LANGUAGE_NAMES` dict and `ISO_639_RE` regex from `episodes/summarizer.py` into a shared module. Both summarizer and extractor import from here, eliminating duplication.

- **Extractor task** (`episodes/extractor.py`): New module with `extract_entities(episode_id)`. Loads entity types from YAML at module level. Builds a language-aware system prompt listing all entity types. Dynamically generates a JSON response schema where each entity type key maps to an array of `{name, context}` objects (or null). Calls `provider.structured_extract()`, stores result in `entities_json`, and advances to `RESOLVING`. Errors set status to `FAILED`.

- **Extraction provider factory** (`episodes/providers/factory.py`): Added `get_extraction_provider()` reading from `RAGTIME_EXTRACTION_*` settings, independent from summarization and scraper providers.

- **Signal-driven chaining** (`episodes/signals.py`): Extended `queue_next_step` to detect `EXTRACTING` status and queue the extractor task.

- **Admin** (`episodes/admin.py`): Added `entities_json` as a read-only field in a collapsible "Entities" fieldset, shown when populated.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_EXTRACTION_PROVIDER` | `openai` (default) | Same provider abstraction as other pipeline steps |
| `RAGTIME_EXTRACTION_MODEL` | `gpt-4.1-mini` (default) | Good structured extraction capability at low cost |
| `RAGTIME_EXTRACTION_API_KEY` | (empty default) | Must be set in `.env`; separate key allows different accounts |
| Entity types | 15 types in YAML | Covers artists, bands, albums, compositions, venues, sessions, labels, years, eras, cities, countries, sub-genres, instruments, roles |
| Schema format | `strict: true`, nullable arrays | Enforces structured output; null for empty categories |

## Verification

```bash
# Run all tests (68 total: 55 existing + 13 new)
uv run python manage.py test episodes

# End-to-end: start server + worker, create episode via admin
uv run python manage.py runserver   # Terminal 1
uv run python manage.py qcluster   # Terminal 2

# Expected flow: ... → summarizing → extracting → resolving
# Check admin detail view for Entities section (collapsible JSON)
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/entity_types.yaml` | New — 15 entity type definitions in YAML |
| `episodes/languages.py` | New — shared language utilities |
| `episodes/summarizer.py` | Import language utils from `episodes/languages.py` |
| `episodes/models.py` | Added `entities_json` JSONField |
| `episodes/extractor.py` | New — entity extraction task module |
| `episodes/providers/factory.py` | Added `get_extraction_provider()` factory function |
| `ragtime/settings.py` | Added `RAGTIME_EXTRACTION_PROVIDER`, `_API_KEY`, `_MODEL` settings |
| `episodes/signals.py` | Extended signal for `EXTRACTING` status transitions |
| `episodes/admin.py` | Added `entities_json` to readonly fields and conditional fieldset |
| `episodes/tests.py` | 13 new tests (3 prompt + 1 schema + 8 extractor + 1 signal) |
| `episodes/migrations/0006_episode_entities_json.py` | Migration for `entities_json` field |
| `README.md` | Added extraction config vars, entity type table, features entry |
| `pyproject.toml` / `uv.lock` | Added `pyyaml` dependency |
