# Session: Chunk-level Entity Extraction — Planning

**Date:** 2026-03-15

**Session ID:** d8df4186-a362-415c-9d05-bc068bbd5fd0

## Summary

Planned the transition from episode-level entity extraction to chunk-level extraction, so each entity mention is linked to the specific chunk (and timestamp) where it appeared.

## Conversation

### Assistant

Already on `main`. Pulling latest changes.

On `main`, already up to date. Ready to go.

### User

Let's focus on the "Extract" step. Yesterday we moved the chunking step before the Extract and Resolve steps. The current extraction and resolve logic operates at the episode transcript level and not at the chunk level. Since we will need to link the entities back to the place in the episode where they were mentioned we will need to change that logic to operate at the chunk level. Analyize the current implementation and provide pros and cons about switching to extraction and resolving at the chunk level. Please note that in the future we also want to be able to show users, for a given episodes which resolved entities are mentioned in that episode.

### Assistant

Let me explore the current extraction and resolution implementation.

Now let me read a few key files to confirm details before designing the plan.

Now let me design the approach with a Plan agent.

Now let me write the plan file.

Here's the summary of the analysis:

**Key tradeoff:** Chunk-level extraction costs ~40-60 LLM calls per episode (vs 1 today), but each call uses only ~150 words of input, so the cost increase is moderate. The payoff is entity-to-timestamp provenance and better RAG alignment.

**Recommended hybrid approach:** Extract per-chunk (for provenance), but resolve once per entity type across the whole episode (same resolution cost as today). This gives chunk-level linking without multiplying resolution calls.

**Main model changes:**
- `Chunk.entities_json` — stores per-chunk extraction output
- `EntityMention.chunk` FK — links each mention to its source chunk
- Unique constraint shifts from `(entity, episode, context)` to `(entity, chunk)`

**Context quality concern:** 150 words is usually enough for named entity extraction (names, places, albums are self-evident), though some entities that require broader context (e.g., an ambiguous pronoun reference) might be missed. This is a minor risk given the use case (jazz podcasts with explicit entity names).

### User

[Request interrupted by user for tool use]
