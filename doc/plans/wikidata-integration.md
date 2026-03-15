# Plan: Add Wikidata Integration to Extract & Resolve Steps

## Context

The current Extract (step 7) and Resolve (step 8) pipeline steps use LLM-based extraction and fuzzy matching. This works well but entities lack canonical identifiers. We want to:
1. Use **Wikidata Q-IDs** as canonical entity identifiers
2. Enhance the LLM resolver with **Wikidata API candidate lookup** so it can assign Q-IDs
3. Add a management command to look up entities in Wikidata
4. Rename pipeline sections: "Extract" → "Extract entities", "Resolve" → "Resolve entities"

The LLM-based extraction and resolution approach stays. No GLiNER or alternative NER providers in this iteration — those are deferred to a future plan.

## 1. Model Changes

| Model | Field | Type | Notes |
|-------|-------|------|-------|
| `EntityType` | `wikidata_id` | `CharField(max_length=20, blank=True, default="")` | Wikidata class Q-ID (e.g., Q639669 for "musician") |
| `Entity` | `wikidata_id` | `CharField(max_length=20, blank=True, default="", db_index=True)` | Specific entity Q-ID (e.g., Q93341 for "Miles Davis") |

No uniqueness constraint on `wikidata_id` — the existing `(entity_type, name)` constraint handles dedup.

## 2. YAML + load_entity_types

Add `wikidata_id` per entry in `episodes/initial_entity_types.yaml`. Update `load_entity_types` command to include `wikidata_id` in defaults.

## 3. Wikidata Client Module

New file: `episodes/wikidata.py` — utility module for querying the Wikidata API with functions:
- `search_entities()` — wbsearchentities API
- `get_entity()` — wbgetentities API
- `find_candidates()` — search + P31 filtering

Caching via Django database cache backend, 7-day TTL.

## 4. Resolver Changes

The resolver gains a Wikidata candidate lookup step before LLM resolution:
1. Fetch Wikidata candidates for each entity name
2. Pass candidates to LLM prompt for confirmation
3. Resolution priority: wikidata_id match → DB entity ID match → create new

## 5. Management Command

`lookup_entity` — search Wikidata from CLI, optionally filtered by entity type.

## 6. Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `RAGTIME_WIKIDATA_USER_AGENT` | `RAGtime/0.1 (...)` | Required by Wikidata API policy |
| `RAGTIME_WIKIDATA_CACHE_TTL` | `604800` | 7-day cache TTL |

## 7. README Updates

Rename sections and update descriptions to mention Wikidata integration.
