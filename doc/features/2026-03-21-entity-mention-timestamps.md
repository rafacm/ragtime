# Add Timestamps to Entity Mentions

**Date:** 2026-03-21

## Problem

Entity mentions stored the chunk where an entity was extracted but not the precise timestamp within the episode. Users could not jump directly to where an entity is mentioned in a podcast.

## Changes

- **EntityMention model** — added nullable `start_time` FloatField to store the timestamp (in seconds) where the entity is first mentioned within its chunk.
- **`episodes/timestamps.py`** (new) — pure function `find_entity_start_time()` that matches an entity name against Whisper word-level timestamps using a sliding window. Tries full consecutive-token match first, falls back to matching the entity's first token.
- **Extractor** — after LLM extraction per chunk, `_annotate_timestamps()` resolves each entity's timestamp from the episode's word-level transcript data and writes it into `entities_json`.
- **Resolver** — `_aggregate_entities_from_chunks()` and `_collect_mentions()` now carry `start_time` through to EntityMention records.
- **Admin** — `start_time` displayed in all EntityMention inlines and the EntityMention list view.

## Key parameters

- Word matching is case-insensitive with punctuation stripped (regex `[^\w\s]`).
- Chunk time range filtering uses `[chunk_start, chunk_end)` (inclusive start, exclusive end).
- When no word-level timestamps exist (legacy transcripts), `start_time` falls back to `chunk.start_time`.
- When the entity name is not found in words (LLM inferred it from context), `start_time` is `None`.

## Verification

```bash
uv run python manage.py migrate
uv run python manage.py test episodes
```

All 204 tests pass. Entity mentions visible in the admin with timestamps after processing an episode.

## Files modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `start_time` FloatField to EntityMention |
| `episodes/timestamps.py` | New — `find_entity_start_time()` pure function |
| `episodes/extractor.py` | Added `_annotate_timestamps()`, called after LLM extraction |
| `episodes/resolver.py` | Thread `start_time` through aggregation and mention creation |
| `episodes/admin.py` | Added `start_time` to EntityMention admin inlines and list |
| `episodes/migrations/0019_entitymention_start_time.py` | Migration for new field |
| `episodes/tests/test_timestamps.py` | New — 13 unit tests for word matching |
| `episodes/tests/test_extract.py` | 3 new tests for timestamp annotation |
| `episodes/tests/test_resolve.py` | 3 new tests for start_time flow to EntityMention |
