# Plan: Rename Entity Type Keys to Match Wikidata Labels

**Date:** 2026-03-16

## Problem

Entity type keys and names in `initial_entity_types.yaml` were manually chosen and didn't always match the official Wikidata labels for their associated Q-IDs. One entry (`recording_session` / Q81091849) pointed to a galaxy instead of a recording session. Aligning keys, names, and descriptions with Wikidata ensures consistency and correctness.

## Approach

1. Verify each Wikidata Q-ID via the Wikidata API (`wbgetentities`)
2. For 8 entity types where the Wikidata label differs from the YAML name, update key, name, and description to match Wikidata verbatim
3. Fix the incorrect Q-ID for `recording_session` (Q81091849 galaxy -> Q98216532 recording session)
4. Propagate key renames across all test fixtures, test data, and README

## Key Renames

| Old key | New key | Wikidata ID | Wikidata Label |
|---------|---------|-------------|----------------|
| artist | musician | Q639669 | musician |
| band | musical_group | Q215380 | musical group |
| composition | composed_musical_work | Q207628 | composed musical work |
| venue | music_venue | Q8719053 | music venue |
| label | record_label | Q18127 | record label |
| era | historical_period | Q11514315 | historical period |
| sub_genre | music_genre | Q188451 | music genre |
| instrument | musical_instrument | Q34379 | musical instrument |

## Unchanged Types

- album (Q482994) - already matches
- recording_session (Q-ID fixed to Q98216532)
- year (Q577) - already matches
- city (Q515) - already matches
- country (Q6256) - already matches
- role (Q12737077) - kept as-is

## Impact

- No migration needed: entity types are seeded from YAML at migration time and via `load_entity_types`
- Test fixtures and test data updated to use new keys
- README entity type listings updated
- Extractor and resolver read keys dynamically from DB, so no production code changes needed
