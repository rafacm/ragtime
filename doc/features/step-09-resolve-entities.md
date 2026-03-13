# Step 9: Resolve Entities

## Problem

After extraction (Step 8), episode entities exist only as raw JSON on `Episode.entities_json`. There's no way to query across episodes ("which episodes mention Miles Davis?"), no deduplication (the same artist may be extracted in every episode), and no admin visibility for entities. Additionally, episodes in different languages may extract the same entity with different names (e.g., "Saxophon" in German vs "Saxophone" in English).

## Changes

- **Status rename** (`episodes/models.py`, `episodes/extractor.py`, tests, docs): Renamed `DEDUPLICATING` → `RESOLVING` across the codebase. Added `RunSQL` data migration to update existing rows.

- **Entity model** (`episodes/models.py`): New model with `entity_type` (CharField, indexed), `name` (CharField), and timestamps. UniqueConstraint on `(entity_type, name)` prevents exact duplicates per type while allowing the same name in different types (e.g., "Bebop" as both `era` and `sub_genre`).

- **EntityMention model** (`episodes/models.py`): Join model linking Entity to Episode with a `context` field preserving episode-specific context in the original language. UniqueConstraint on `(entity, episode, context)` prevents duplicates on reprocessing.

- **Resolver task** (`episodes/resolver.py`): `resolve_entities(episode_id)` processes each entity type from `entities_json`. For types with no existing DB entities, creates all as new without an LLM call (common for first episode). For types with existing entities, calls `structured_extract()` to match extracted names against candidates, considering spelling variants, language differences, and abbreviations. All DB writes wrapped in `transaction.atomic()`. Deletes existing mentions before processing for idempotent reprocessing.

- **Resolution provider** (`episodes/providers/factory.py`, `ragtime/settings.py`): Added `get_resolution_provider()` with independent `RAGTIME_RESOLUTION_PROVIDER`, `_API_KEY`, and `_MODEL` settings. Default: openai / gpt-4.1-mini.

- **Configure wizard** (`core/management/commands/_configure_helpers.py`): Added "Resolution" subsystem to the LLM system. Updated description to include resolution.

- **Signal dispatch** (`episodes/signals.py`): `RESOLVING` status triggers `resolve_entities` async task.

- **Admin** (`episodes/admin.py`): Registered `EntityAdmin` with mention count annotation, type filter, and name search. Registered `EntityMentionAdmin` with context preview. Added `EntityMentionInline` to both `EpisodeAdmin` (shows resolved entities per episode) and `EntityAdmin` (shows episodes per entity). All entity admin views are read-only.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_RESOLUTION_PROVIDER` | `openai` (default) | Same provider abstraction as other pipeline steps |
| `RAGTIME_RESOLUTION_MODEL` | `gpt-4.1-mini` (default) | Good fuzzy matching capability at low cost |
| `RAGTIME_RESOLUTION_API_KEY` | (empty default) | Must be set in `.env`; separate key allows different accounts |
| Entity.name max_length | 500 | Accommodates long entity names |
| Entity.entity_type max_length | 30 | Covers all entity type keys with headroom |

## Verification

```bash
# Run all tests (79 total: 68 existing + 11 new)
uv run python manage.py test episodes

# End-to-end: start server + worker, create episode via admin
uv run python manage.py runserver   # Terminal 1
uv run python manage.py qcluster   # Terminal 2

# Expected flow: ... → extracting → resolving → embedding
# Check admin for Entity and EntityMention models
# Process a second episode with overlapping entities to verify deduplication
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Renamed DEDUPLICATING → RESOLVING; added Entity and EntityMention models |
| `episodes/extractor.py` | Updated status transition to RESOLVING |
| `episodes/tests/test_extract.py` | Updated status assertion |
| `episodes/migrations/0007_alter_episode_status_entity_entitymention.py` | RunSQL data migration + AlterField + CreateModel |
| `ragtime/settings.py` | Added RAGTIME_RESOLUTION_PROVIDER, _API_KEY, _MODEL |
| `episodes/providers/factory.py` | Added get_resolution_provider() |
| `core/management/commands/_configure_helpers.py` | Added Resolution subsystem to LLM system |
| `episodes/resolver.py` | New — entity resolution task module |
| `episodes/signals.py` | Added RESOLVING status dispatch |
| `episodes/admin.py` | Registered Entity, EntityMention; added inlines to EpisodeAdmin and EntityAdmin |
| `episodes/tests/fixtures/wdr-giant-steps-django-reinhardt-episode-extracted-entities.json` | New — real extracted entities fixture (59 entities from German podcast episode) |
| `episodes/tests/test_resolve.py` | New — 10 resolution tests using fixture data, including full-fixture idempotent reprocessing test |
| `episodes/tests/test_signals.py` | Added RESOLVING signal test |
| `README.md` | Updated pipeline status, added resolution env vars and Features entry |
| `doc/plans/step-08-extract-entities.md` | DEDUPLICATING → RESOLVING |
| `doc/features/step-08-extract-entities.md` | DEDUPLICATING → RESOLVING |
| `doc/features/step-01-submit-episode.md` | Updated status length rationale |
| `doc/plans/step-01-submit-episode.md` | DEDUPLICATING → RESOLVING |
