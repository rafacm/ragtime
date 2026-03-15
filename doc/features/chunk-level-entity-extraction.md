# Chunk-level Entity Extraction & Resolution

## Problem

Entity extraction ran on the full episode transcript as one LLM call, storing results in `episode.entities_json`. Entity mentions were linked only to episodes, with no provenance about *where* in the episode an entity appeared. Since chunks already have timestamps, extracting per-chunk gives us positional context for free.

## Changes

| File | Change |
|------|--------|
| `episodes/models.py` | Added `Chunk.entities_json` (JSONField); added `EntityMention.chunk` FK; replaced unique constraint from `(entity, episode, context)` to `(entity, chunk)` |
| `episodes/migrations/0016_chunk_level_extraction.py` | Multi-step migration: add fields, delete existing mentions, make chunk non-nullable, swap constraints |
| `episodes/extractor.py` | Validate chunks exist (not transcript); loop over chunks calling provider per chunk; store in `chunk.entities_json`; bulk_update; updated system prompt to say "transcript excerpt" |
| `episodes/resolver.py` | Aggregate entities from `chunk.entities_json` across all chunks; resolve unique names per type; create `EntityMention` per (entity, chunk) pair; treat "no entities" as success |
| `episodes/admin.py` | Added `chunk` to readonly fields on `EntityMentionInlineForEpisode`, `EntityMentionInlineForEntity`, and `EntityMentionAdmin` |
| `episodes/tests/test_extract.py` | Tests create chunks; verify `chunk.entities_json` populated; N chunks → N LLM calls; "no chunks" → failure |
| `episodes/tests/test_resolve.py` | Tests use chunks with `entities_json`; verify chunk FKs on mentions; test same entity in multiple chunks → multiple mentions; test aggregation (one resolution call) |
| `README.md` | Updated Extract and Resolve step descriptions |

## Verification

1. `uv run python manage.py migrate` — applies cleanly
2. `uv run python manage.py test episodes` — all 102 tests pass
3. Admin: EntityMention inlines and list view show chunk column
