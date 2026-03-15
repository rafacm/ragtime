# Wikidata Integration — Planning Session

## Session ID
338ce28e-0518-499d-9202-0e280fe151bd

## Summary
Planned the addition of Wikidata Q-ID integration to the Extract and Resolve pipeline steps, including model changes, Wikidata API client, resolver enhancements, management command, and configuration updates.

### User
Entered plan mode and requested a plan for adding Wikidata integration to the entity extraction and resolution pipeline.

### Assistant
Explored the codebase to understand the current entity extraction and resolution implementation. Read `episodes/models.py`, `episodes/resolver.py`, `episodes/initial_entity_types.yaml`, `episodes/extractor.py`, and related files.

Considered several approaches:
- **GLiNER-based NER** — deferred to future iteration due to complexity
- **Wikidata as canonical identifier source** — chosen as the approach for this iteration
- **Provider abstraction for Wikidata** — decided against; Wikidata is a utility, not a pluggable provider

Key design decisions:
1. `wikidata_id` as informational field, not uniqueness constraint — existing `(entity_type, name)` handles dedup
2. Wikidata candidate lookup happens *before* LLM resolution, candidates passed to LLM for confirmation
3. LLM can return `null` for `wikidata_id` if no candidates match — graceful degradation
4. Database cache backend for Wikidata API responses (7-day TTL)
5. Resolution priority: wikidata_id DB match → entity ID match → create new

### User
Reviewed the plan, requested recording_session Q-ID research and rename of pipeline sections.

### Assistant
Researched Wikidata Q-IDs for all 14 entity types. Found Q81091849 for recording session. Updated plan with section renames: "Extract" → "Extract entities", "Resolve" → "Resolve entities".

### User
Accepted the plan.

### Assistant
Saved the plan to `doc/plans/wikidata-integration.md`.
