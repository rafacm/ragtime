# Decouple Wikidata Linking into a Background Linking Agent

**Date:** 2026-03-31

## Problem

The resolve pipeline step calls the Wikidata API synchronously for every entity name. `find_candidates()` makes up to 11 HTTP requests per entity (1 search + 10 `get_entity` calls, each with 10s timeout). For episodes with many entities across multiple types, this causes timeouts and can exhaust the 900s Django Q2 task timeout.

The `wikidata_id` is not used in embedding or RAG queries — only for cross-episode deduplication and admin display. The codebase already handles missing `wikidata_id` gracefully.

## Alternatives Considered

- **YAGO3/4**: Built from Wikidata, similarly large (64M entities), still requires external API calls — doesn't solve the timeout problem.
- **MusicBrainz**: Domain-specific for music, good jazz coverage. Better as a future supplementary source, separate from this change.
- **DBpedia**: Similar scale to Wikidata, not meaningfully smaller.
- **Jazz Ontology / Linked Jazz**: Academic RDF datasets, limited scope and unclear API availability.

## Chosen Approach

1. Remove Wikidata API calls from the resolver — pure LLM-based entity resolution using existing DB records
2. Create a background linking agent (Pydantic AI) that asynchronously enriches entities with Wikidata Q-IDs after the pipeline completes
3. The linking agent follows the same architectural pattern as the existing recovery agent

## Key Design Decisions

- **Not a pipeline step**: The linking agent is triggered by `step_completed` signal but does not appear in `PIPELINE_STEPS`. The pipeline continues to embedding immediately.
- **Agent pattern**: Uses Pydantic AI with tools (`search_wikidata`, `link_entity`, `mark_failed`, `skip_entity`) for LLM-based disambiguation of Wikidata candidates.
- **Entity-level tracking**: `linking_status` field on `Entity` model tracks state (pending/linked/skipped/failed).
- **Batch processing**: Configurable batch size, queues follow-up tasks when more pending entities remain.
