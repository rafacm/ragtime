# Feature: Rename Entity Type Keys to Match Wikidata Labels

## Problem

Entity type keys in `initial_entity_types.yaml` used informal names (e.g., "artist", "band", "label") that didn't match the official Wikidata labels for their associated Q-IDs. Additionally, the `recording_session` entry (Q81091849) pointed to a galaxy in the constellation Virgo, not a recording session.

## Changes

- **8 entity types renamed** — keys, names, and descriptions updated to match Wikidata labels verbatim (e.g., `artist` -> `musician`, `band` -> `musical_group`)
- **1 Q-ID fixed** — `recording_session` changed from Q81091849 (galaxy) to Q98216532 (recording session)
- **Examples adjusted** — added examples where appropriate (e.g., Thelonious Monk, Weather Report, Blue Note Jazz Club); replaced "Post-Bop" in historical_period with "The Harlem Renaissance"
- **Test data updated** — all test fixtures and inline test data use new keys
- **README updated** — entity type listings in Features and Extract sections

## Key Parameters

No tunable constants. Names and descriptions for the 8 renamed types come from Wikidata API responses. Types that were not renamed (e.g., `recording_session`, `album`, `year`) retain their existing descriptions and examples.

**Note:** This project has not been released yet, so there are no existing installs to migrate. A fresh `migrate` + `load_entity_types` is sufficient.

## Verification

```bash
uv run python manage.py test                    # All 150 tests pass
rm db.sqlite3 && uv run python manage.py migrate  # Fresh DB gets new keys
uv run python manage.py load_entity_types        # Verify new names in admin
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/initial_entity_types.yaml` | 8 key/name/description renames, 1 Q-ID fix, example adjustments |
| `episodes/tests/fixtures/wdr-giant-steps-django-reinhardt-episode-extracted-entities.json` | JSON keys renamed to match new entity type keys |
| `episodes/tests/test_extract.py` | SAMPLE_ENTITIES keys, schema test, prompt assertions updated |
| `episodes/tests/test_resolve.py` | `_get_entity_type()` calls and inline test data updated |
| `README.md` | Entity type listings in Features and Extract sections updated |
