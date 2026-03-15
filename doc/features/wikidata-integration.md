# Feature: Wikidata Integration for Entity Resolution

## Problem

Entities extracted from podcast episodes lacked canonical identifiers. Two different episodes mentioning "Miles Davis" could confirm they refer to the same real-world entity only through name matching — no stable external ID tied them together.

## Changes

### Model changes
- Added `wikidata_id` field to `EntityType` (Wikidata class Q-ID, e.g., Q639669 for "musician")
- Added `wikidata_id` field to `Entity` (specific entity Q-ID, e.g., Q93341 for "Miles Davis"), with `db_index=True`
- Single additive migration, no data loss

### YAML seed data
- Added `wikidata_id` to all 14 entity types in `initial_entity_types.yaml`
- Updated `load_entity_types` command to persist `wikidata_id`

### Wikidata client (`episodes/wikidata.py`)
- `search_entities()` — search via wbsearchentities API
- `get_entity()` — fetch full entity details via wbgetentities API
- `find_candidates()` — search + P31 (instance of) filtering to match entity type class
- Database cache backend with configurable TTL (default 7 days)

### Resolver changes (`episodes/resolver.py`)
- Before LLM resolution, fetches Wikidata candidates for each entity name
- Candidates (Q-IDs + descriptions) included in the LLM system prompt
- Resolution response schema extended with `wikidata_id` field
- Resolution priority: (1) match by `wikidata_id` in DB, (2) match by entity ID, (3) create new
- Graceful degradation: if Wikidata API is unreachable, falls back to existing behavior

### Management command (`lookup_entity`)
- `manage.py lookup_entity "Miles Davis"` — general search
- `manage.py lookup_entity --type artist "Miles Davis"` — filtered by entity type's Wikidata class

### Admin
- `wikidata_id` displayed in EntityType and Entity admin views

### Settings
- `RAGTIME_WIKIDATA_USER_AGENT` — User-Agent for Wikidata API (required by policy)
- `RAGTIME_WIKIDATA_CACHE_TTL` — cache TTL in seconds (default: 604800 = 7 days)
- Database cache backend configured for `wikidata` alias

### README
- Renamed "Extract" → "Extract entities", "Resolve" → "Resolve entities"
- Updated descriptions to mention Wikidata candidate lookup and Q-IDs

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Cache TTL | 604800s (7 days) | Wikidata entities rarely change; reduces API load |
| Search limit | 10 candidates | Broad enough to find matches, narrow enough for P31 filtering |
| P31 filtering | Instance-of check | Ensures candidates match the expected entity type class |

## Verification

1. Migration applies cleanly: `uv run python manage.py migrate`
2. YAML loads with wikidata_ids: `uv run python manage.py load_entity_types`
3. Cache table created: `uv run python manage.py createcachetable`
4. Wikidata lookup works: `uv run python manage.py lookup_entity "Miles Davis"`
5. All tests pass: `uv run python manage.py test episodes`

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `wikidata_id` to EntityType and Entity |
| `episodes/initial_entity_types.yaml` | Added `wikidata_id` per entry |
| `episodes/management/commands/load_entity_types.py` | Include `wikidata_id` in defaults |
| `episodes/wikidata.py` | New — Wikidata API client with caching |
| `episodes/resolver.py` | Wikidata candidate lookup before LLM resolution |
| `episodes/management/commands/lookup_entity.py` | New — CLI Wikidata search |
| `episodes/admin.py` | Show `wikidata_id` in EntityType and Entity admin |
| `ragtime/settings.py` | Wikidata settings, cache configuration |
| `.env.sample` | New env vars |
| `core/management/commands/_configure_helpers.py` | Wikidata section in wizard |
| `episodes/tests/test_resolve.py` | Updated for wikidata_id in schema, new Wikidata tests |
| `episodes/tests/test_wikidata.py` | New — Wikidata client tests |
| `episodes/migrations/0017_entity_wikidata_id_entitytype_wikidata_id.py` | Migration |
| `README.md` | Renamed sections, updated descriptions |
| `CHANGELOG.md` | New entry |
