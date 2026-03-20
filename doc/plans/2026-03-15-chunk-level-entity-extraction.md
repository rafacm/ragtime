# Chunk-level Entity Extraction & Resolution

**Date:** 2026-03-15

## Context

The pipeline currently runs extraction on the full `episode.transcript` and stores results in `episode.entities_json`. Resolution then creates `EntityMention` records linked to episodes. Since chunking now runs **before** extraction, we can extract per-chunk, linking each entity mention to the specific chunk (and thus timestamp) where it appeared.

## Approach

- **Extraction** runs per-chunk (one LLM call per chunk).
- **Resolution** aggregates unique entity names across all chunks, then resolves once per entity type against the DB (same LLM call count as today for resolution).
- **EntityMention** records are created per (entity, chunk) pair.

### Flow

```
chunks ──► extract per chunk ──► aggregate unique names ──► resolve per type ──► create mentions per chunk
```

## Model Changes

| Model | Change |
|-------|--------|
| `Chunk` | Add `entities_json = JSONField(blank=True, null=True)` |
| `EntityMention` | Add `chunk = ForeignKey(Chunk, CASCADE)`, replace unique constraint `(entity, episode, context)` with `(entity, chunk)` |
| `Episode.entities_json` | Stop writing to it; keep field for now |

## Migration Strategy

1. Add `Chunk.entities_json`
2. Add `EntityMention.chunk` (nullable initially)
3. Data migration: delete all existing EntityMention rows
4. Make `EntityMention.chunk` non-nullable
5. Drop old unique constraint, add new `(entity, chunk)`

## Extractor Changes

- Validate chunks exist (instead of `episode.transcript`)
- Loop over chunks, call provider per chunk
- Store result in `chunk.entities_json`
- `bulk_update` all chunks

## Resolver Changes

- **Phase A — Aggregate:** Collect `{type_key: {name: [(chunk, context), ...]}}` across all chunks
- **Phase B — Resolve:** For each entity type, same logic as today with unique names
- **Phase C — Create mentions:** `EntityMention(entity=..., episode=..., chunk=..., context=...)` per (name, chunk, context) triple
- Handle "no entities in any chunk" as success (not failure)

## Trade-offs

| | Episode-level (current) | Chunk-level (proposed) |
|---|---|---|
| **LLM calls** | 1 per episode | ~40-60 per episode |
| **Entity provenance** | None | Chunk + timestamp |
| **RAG alignment** | Disconnected | Shared unit |
| **Cost** | Lower | Higher, but inputs are small |
