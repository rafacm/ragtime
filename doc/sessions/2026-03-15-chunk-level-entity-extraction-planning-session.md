# Session: Chunk-level Entity Extraction — Planning

**Session ID:** d8df4186-a362-415c-9d05-bc068bbd5fd0
**Date:** 2026-03-15

## Summary

Planned the transition from episode-level entity extraction to chunk-level extraction, so each entity mention is linked to the specific chunk (and timestamp) where it appeared.

## Conversation

### User
Requested analysis of switching extraction and resolution from episode-level to chunk-level. Since chunking now runs before extraction, we should link entities back to where in the episode they were mentioned. Also noted a future requirement: showing users which resolved entities appear in a given episode.

### Assistant
Explored the current extraction (`episodes/extractor.py`) and resolution (`episodes/resolver.py`) implementation. Key findings:

- Extraction runs on `episode.transcript` (full text), stores result in `episode.entities_json`
- Resolution iterates `episode.entities_json`, creates `EntityMention` records linked only to episodes
- `EntityMention` has unique constraint on `(entity, episode, context)` — no chunk linkage
- Chunks have `text`, `start_time`, `end_time` fields — ideal for provenance

Presented pros and cons comparison:

- **Episode-level pros:** Fewer LLM calls (1 per episode), full transcript context for disambiguation
- **Chunk-level pros:** Entity provenance with timestamps, RAG alignment (entities and embeddings share the same unit), enables "entities per episode with position" queries
- **Chunk-level cons:** More LLM calls (~40-60 per episode), less cross-chunk context for disambiguation

Recommended approach: extract per-chunk (provenance is the point), then aggregate unique names and resolve once per entity type (same resolution cost as today). `EntityMention` records created per (entity, chunk) pair.

Proposed model changes: `Chunk.entities_json` for raw extraction, `EntityMention.chunk` FK, constraint change from `(entity, episode, context)` to `(entity, chunk)`. Multi-step migration with data migration to delete existing mentions.

Proposed handling "no entities in any chunk" as success (not failure), since it's a valid state.

### User
Approved the plan.
