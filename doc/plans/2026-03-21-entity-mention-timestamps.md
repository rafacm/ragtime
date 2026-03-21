# Add Timestamps to Entity Mentions

**Date:** 2026-03-21

## Context

EntityMention records link an entity to the chunk where it was mentioned, but have no precise timestamp. Users need to jump directly to where an entity is mentioned in a podcast episode. The transcription provider already requests word-level timestamps (`timestamp_granularities: ["word", "segment"]`), so we have the data — we just need to resolve and store it.

## Approach

Add timestamps during the **extraction step** (post-LLM processing), not during resolution. The extractor already processes per-chunk and has access to the chunk's time range, making it the natural place to match entity names against word-level timestamps. The resolver simply passes the timestamp through to the EntityMention record.

## Changes

| # | Change | File |
|---|--------|------|
| 1 | Add `start_time = FloatField(null=True, blank=True)` to EntityMention | `episodes/models.py` |
| 2 | New pure function `find_entity_start_time()` — sliding window word match with partial fallback | `episodes/timestamps.py` |
| 3 | `_annotate_timestamps()` helper called after LLM extraction per chunk | `episodes/extractor.py` |
| 4 | Thread `start_time` through aggregation and mention creation | `episodes/resolver.py` |
| 5 | Show `start_time` in admin inlines | `episodes/admin.py` |

## Matching algorithm

1. Filter words to chunk time range `[chunk_start, chunk_end)`
2. Normalize: lowercase, strip punctuation
3. **Full match first:** sliding window over consecutive word tokens
4. **Partial fallback:** if no full match, match entity's first token only
5. Return `start` of first match, or `None`

## Fallback behavior

| Case | `start_time` value |
|------|--------------------|
| Word timestamps available, entity found | Matched word's `start` |
| Word timestamps available, entity not found | `None` |
| No word timestamps (legacy transcript) | `chunk.start_time` |
