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

### User
Requested clickable Episode link in EntityMention admin list view.

### Assistant
Added `episode_link` method using `reverse("admin:episodes_episode_change", ...)` to `EntityMentionAdmin`, replacing the plain `episode` column.

### User
Asked whether Chunks should be exposed in Django admin.

### Assistant
Proposed registering a read-only `ChunkAdmin` with entity mention inline, plus clickable chunk links in `EntityMentionAdmin`. User approved.

### Assistant
- Registered `ChunkAdmin` with `episode_link`, `formatted_time_range`, `short_text`, `has_entities` columns
- Added `EntityMentionInlineForChunk` (excludes episode column since it's on the parent page)
- Added `chunk_link` to `EntityMentionAdmin` list view
- Added `show_change_link = True` to `ChunkInlineForEpisode`

### User
Noted that Entity Mentions inline on Chunk detail should not show Episode column.

### Assistant
Set explicit `fields` on `EntityMentionInlineForChunk` to show only `entity`, `context`, `created_at`.

### User
Requested PR creation.

### Assistant
Created PR #47: https://github.com/rafacm/ragtime/pull/47

### PR Review — Copilot (5 comments)

**Comment 1 — Silent context loss with `ignore_conflicts` (`resolver.py:139-150`):**
`bulk_create(ignore_conflicts=True)` silently drops duplicate `(entity, chunk)` pairs; if the extractor returns the same name twice in a chunk with different contexts, one is lost.
**Fix:** De-duplicated by `(name, chunk)` in `_aggregate_entities_from_chunks()` (keeps first context per chunk). Removed `ignore_conflicts=True` from both `bulk_create` call sites.

**Comment 2 — High-cardinality `list_filter` (`admin.py:274`):**
`list_filter = ("episode__title",)` creates one sidebar entry per unique title.
**Fix:** Changed to `list_filter = ("episode",)` for FK filter widget.

**Comment 3 — Redundant inner import (`extractor.py:121-122`):**
`from .models import Chunk` inside function body when module already imports from `.models`.
**Fix:** Added `Chunk` to top-level import, removed inner import.

**Comment 4 — Missing mention cleanup in early-return path (`resolver.py:103-105`):**
When no chunks/entities exist, stale `EntityMention` rows from a previous run survive.
**Fix:** Added `EntityMention.objects.filter(episode=episode).delete()` before early return.

**Comment 5 — Per-name DB round-trips (`resolver.py:127-138`):**
One `Entity.objects.create()` + one `bulk_create()` per name.
**Fix:** Batched all `EntityMention` objects per entity type into a single `bulk_create`. `Entity.objects.create()` per name kept because SQLite doesn't support `bulk_create` returning IDs.

All 102 tests pass after fixes.
