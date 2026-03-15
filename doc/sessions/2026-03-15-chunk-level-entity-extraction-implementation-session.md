# Session: Chunk-level Entity Extraction — Implementation

**Session ID:** (current session)
**Date:** 2026-03-15

## Summary

Implemented chunk-level entity extraction and resolution, linking each entity mention to the specific chunk where it appeared.

## Conversation

### User
Provided the accepted plan for chunk-level entity extraction and asked to implement it.

### Assistant
Read all critical files: `episodes/models.py`, `episodes/extractor.py`, `episodes/resolver.py`, `episodes/admin.py`, and both test files.

**Model changes (`episodes/models.py`):**
- Added `entities_json = JSONField(blank=True, null=True)` to `Chunk`
- Added `chunk = ForeignKey("Chunk", CASCADE, related_name="entity_mentions")` to `EntityMention`
- Replaced unique constraint from `(entity, episode, context)` to `(entity, chunk)`

**Migration (`0016_chunk_level_extraction.py`):**
- Wrote a multi-step migration: add `Chunk.entities_json`, add `EntityMention.chunk` as nullable, data migration to delete all existing mentions, make chunk non-nullable, swap constraints. Chose manual migration over auto-generated because Django can't auto-create a non-nullable FK without a default.

**Extractor changes (`episodes/extractor.py`):**
- Changed validation from checking `episode.transcript` to checking for chunks
- Added loop over chunks, calling `provider.structured_extract` per chunk with `chunk.text`
- Used `Chunk.objects.bulk_update` to persist all `entities_json` in one DB call
- Updated system prompt wording from "transcript" to "transcript excerpt"

**Resolver changes (`episodes/resolver.py`):**
- Added `_aggregate_entities_from_chunks()` to collect `{type_key: {name: [(chunk, context), ...]}}` across all chunks
- Changed resolution to use aggregated unique names per type (same LLM call count as before)
- Creates `EntityMention` per (entity, chunk) pair using `bulk_create(ignore_conflicts=True)`
- Changed "no entities" from failure to success — transitions to EMBEDDING

**Admin changes (`episodes/admin.py`):**
- Added `chunk` to readonly fields on `EntityMentionInlineForEpisode`, `EntityMentionInlineForEntity`, and `EntityMentionAdmin`

**Tests:**
- Updated `test_extract.py`: tests create chunks, verify `chunk.entities_json` populated, N chunks → N LLM calls, "no chunks" → failure
- Updated `test_resolve.py`: tests use chunks with `entities_json`, verify chunk FKs on mentions, test same entity in multiple chunks → multiple mentions, test aggregation (one resolution call with unique names), "no entities in any chunk" → success

**README:** Updated Extract and Resolve step descriptions.

All 102 tests pass. Migration applies cleanly. No pending migrations.
