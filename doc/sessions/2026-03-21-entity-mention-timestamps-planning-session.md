# Entity Mention Timestamps — Planning Session

**Date:** 2026-03-21

**Session ID:** 438617e8-2ff9-4481-abaf-6bed9198c9f8

## Summary

Planned adding `start_time` to EntityMention records so users can jump directly to where an entity is mentioned in a podcast episode. The transcription provider already requests word-level timestamps, so the approach resolves entity names against those timestamps during the extraction step using a sliding window match with partial fallback.

### User

Currently for entity mentions, we keep a reference to the chunck whre that entity was extracted but we do NOT keep the timestamp. We need that information so that we can later skip directly to where that entity is mentioned in the podcast episode. When we generate the episode transcript we request both segment- and word-level timestamps. Therefore when extracting an entity mention from a chunck, we can also resolve the timestampt for that entity mention. Provide a plan which includes details about the test cases we will write to test this change. The test cases could use one of the existing episode transcript JSON files already available for the tests.

### Assistant

Launched two Explore agents in parallel to understand:
1. Entity models, extraction process, chunk creation, and how entity mentions relate to chunks
2. Transcript format, test fixtures, chunking code, and existing test infrastructure

Key findings from exploration:
- EntityMention has entity, episode, chunk, context fields — no timestamp
- Chunks have start_time, end_time, segment_start, segment_end
- Extraction step stores `{name, context}` per entity in chunk.entities_json
- Resolution step creates EntityMention records from chunk.entities_json via `_collect_mentions()`
- OpenAI provider requests `timestamp_granularities: ["word", "segment"]`
- Transcript fixtures have segment-level timestamps but NOT word-level
- test_transcribe.py has SAMPLE_WHISPER_RESPONSE with word-level timestamps inline

Read key files: extractor.py, resolver.py (lines 118-167), transcript fixture, test_extract.py, test_resolve.py.

Launched a Plan agent to design the implementation. The agent recommended resolving timestamps during the extraction step (post-LLM, per chunk) rather than during resolution, because the extractor already processes per-chunk and has access to the chunk's time range.

Designed a new `episodes/timestamps.py` module with `find_entity_start_time()` — a pure function using sliding window word matching. The extractor calls `_annotate_timestamps()` after LLM extraction per chunk. The resolver threads `start_time` through to EntityMention.

### User

Regarding "10. Partial match rejected — 'Miles Davis' when only 'Miles' present (no 'Davis' following) → None", why do we reject a partial match?

### Assistant

Good question. The concern with partial matching is false positives — "Miles" alone could match a different entity. But for this use case, the entity name comes from the LLM extraction, so we already know "Miles Davis" is an entity mentioned in that chunk. The question is just where in the chunk it appears.

Asked the user: When the full entity name isn't found as consecutive words but a partial match exists, should we use the partial match's timestamp or return None?

### User

Accept partial match when no previous full or better match was found.

### Assistant

Updated the plan to reflect this: the matching algorithm tries full match first, then falls back to partial (first word of the entity name). Updated test case 10 accordingly.
