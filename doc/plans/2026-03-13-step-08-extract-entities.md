# Step 8: Entity Extraction — Implementation Plan

**Date:** 2026-03-13

## Context

The pipeline currently runs through Step 7 (Summarize), which sets status to `EXTRACTING`. Step 8 picks up from there, extracts jazz entities from the transcript using an LLM, and stores the structured JSON result on the Episode model. The entity types are defined in `episodes/entity_types.yaml` and the extraction prompt is language-aware. The LLM/model for extraction is independently configurable.

## Changes

### 1. Entity type definitions: `episodes/entity_types.yaml`

YAML file defining 15 entity types with `key`, `name`, `description`, and `examples` fields. Keys are snake_case identifiers used as JSON property names.

### 2. Shared language module: `episodes/languages.py`

Extract `ISO_639_LANGUAGE_NAMES` and `ISO_639_RE` from `episodes/summarizer.py` into a shared module. Both summarizer and extractor import from there.

### 3. Model field: `episodes/models.py`

Add `entities_json` JSONField (nullable, blank) to store extracted entities.

### 4. Extractor module: `episodes/extractor.py`

- Load entity types from YAML at module level
- `build_system_prompt(language)` — language-aware prompt with entity type definitions
- `build_response_schema()` — dynamic JSON schema from entity types
- `extract_entities(episode_id)` — task function: validate status, call `structured_extract()`, store result, advance to `RESOLVING`

### 5. Settings: `ragtime/settings.py`

Add `RAGTIME_EXTRACTION_PROVIDER`, `_API_KEY`, `_MODEL` (defaults: openai, gpt-4.1-mini).

### 6. Factory: `episodes/providers/factory.py`

Add `get_extraction_provider()`.

### 7. Signal: `episodes/signals.py`

Dispatch `EXTRACTING` status to `extract_entities` task.

### 8. Admin: `episodes/admin.py`

Add `entities_json` to readonly fields with collapsible "Entities" fieldset.

### 9. Tests

- `build_system_prompt` with/without language
- `build_response_schema` structure validation
- `extract_entities` happy path, missing transcript, wrong status, nonexistent episode, provider error
- Signal dispatch for EXTRACTING status

### 10. README updates

- Three new `RAGTIME_EXTRACTION_*` env vars in Configuration
- "Extracted Entities" section with entity type table
- Features & Fixes entry

## Files to modify/create

| File | Action |
|------|--------|
| `episodes/entity_types.yaml` | Create |
| `episodes/languages.py` | Create |
| `episodes/summarizer.py` | Edit — import from languages.py |
| `episodes/models.py` | Edit — add entities_json |
| `episodes/extractor.py` | Create |
| `episodes/providers/factory.py` | Edit — add get_extraction_provider() |
| `ragtime/settings.py` | Edit — add RAGTIME_EXTRACTION_* |
| `episodes/signals.py` | Edit — add EXTRACTING dispatch |
| `episodes/admin.py` | Edit — add entities_json fieldset |
| `episodes/tests.py` | Edit — add extraction tests |
| `README.md` | Edit — config, entity table, features |
| `episodes/migrations/0006_*.py` | Create — migration |
