# Step 9: Entity Resolution — Implementation Plan

**Date:** 2026-03-13

## Context

Step 8 (Extract) stores raw LLM-extracted entities as JSON on `Episode.entities_json`. These entities are not yet persisted as database records, so there's no way to query across episodes ("which episodes mention Miles Davis?"), no deduplication across episodes, and no admin visibility. Step 9 resolves extracted entities against existing DB records using LLM-based fuzzy matching, creates canonical `Entity` rows, and links them to episodes via `EntityMention` with episode-specific context.

Episodes can be in different languages (German, English, etc.), so the same entity may appear with different names across episodes (e.g., "Saxophon" vs "Saxophone"). The LLM picks the best canonical name during resolution.

## Changes

### 1. Rename status `DEDUPLICATING` → `RESOLVING`

The current status name `deduplicating` doesn't accurately describe this step. Renamed across the codebase: model choices, extractor transition, tests, docs, and README pipeline table. Added a `RunSQL` data migration to update any existing rows.

### 2. Data model: `Entity` and `EntityMention`

Two new models in `episodes/models.py`:

- **Entity**: `entity_type` (CharField, indexed), `name` (CharField), timestamps. UniqueConstraint on `(entity_type, name)`.
- **EntityMention**: FK to Entity (CASCADE), FK to Episode (CASCADE), `context` (TextField), `created_at`. UniqueConstraint on `(entity, episode, context)`.

### 3. Resolver module: `episodes/resolver.py`

`resolve_entities(episode_id)` — main task function:
1. Validate status is `RESOLVING` and `entities_json` is not empty
2. Delete existing mentions for idempotent reprocessing
3. For each entity type: if no existing entities in DB, create all as new (no LLM call); otherwise call LLM to match against existing
4. LLM returns matched entity IDs or null for new entities, plus canonical names
5. All DB writes in `transaction.atomic()`
6. On success → `EMBEDDING`; on failure → `FAILED`

### 4. Provider configuration

`RAGTIME_RESOLUTION_PROVIDER`, `_API_KEY`, `_MODEL` settings (defaults: openai, gpt-4.1-mini). Factory function `get_resolution_provider()`. Configure wizard updated with "Resolution" subsystem.

### 5. Signal dispatch

`RESOLVING` status triggers `resolve_entities` async task.

### 6. Admin

`EntityAdmin` with mention count annotation, `EntityMentionAdmin` with context preview, and `EntityMentionInline` on both `EpisodeAdmin` and `EntityAdmin`.

### 7. Tests

11 tests covering: new entities, matching existing, mixed, canonical naming, null types, missing entities_json, wrong status, nonexistent episode, provider error, idempotent reprocessing, and signal dispatch.

## Files modified/created

| File | Action |
|------|--------|
| `episodes/models.py` | Edit — rename DEDUPLICATING → RESOLVING, add Entity and EntityMention |
| `episodes/extractor.py` | Edit — DEDUPLICATING → RESOLVING |
| `episodes/tests/test_extract.py` | Edit — update status assertion |
| `episodes/migrations/0007_*.py` | Create — RunSQL + AlterField + CreateModel |
| `ragtime/settings.py` | Edit — add RAGTIME_RESOLUTION_* vars |
| `episodes/providers/factory.py` | Edit — add get_resolution_provider() |
| `core/management/commands/_configure_helpers.py` | Edit — add Resolution subsystem |
| `episodes/resolver.py` | Create — resolution logic |
| `episodes/signals.py` | Edit — add RESOLVING dispatch |
| `episodes/admin.py` | Edit — register Entity, EntityMention, add inlines |
| `episodes/tests/test_resolve.py` | Create — 10 resolution tests |
| `episodes/tests/test_signals.py` | Edit — add RESOLVING signal test |
| `README.md` | Edit — status rename, env vars, Features & Fixes |
| `doc/plans/2026-03-13-step-08-extract-entities.md` | Edit — DEDUPLICATING → RESOLVING |
| `doc/features/2026-03-13-step-08-extract-entities.md` | Edit — DEDUPLICATING → RESOLVING |
| `doc/features/2026-03-09-step-01-submit-episode.md` | Edit — deduplicating → resolving |
| `doc/plans/2026-03-09-step-01-submit-episode.md` | Edit — DEDUPLICATING → RESOLVING |

## Verification

```bash
uv run python manage.py makemigrations    # Verify no pending migrations
uv run python manage.py migrate           # Apply migration
uv run python manage.py test episodes     # 79 tests, all passing
uv run python manage.py check             # Django system checks
```
