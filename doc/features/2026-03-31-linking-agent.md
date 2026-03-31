# Decouple Wikidata Linking into Background Linking Agent

**Date:** 2026-03-31

## Problem

The resolve pipeline step called the Wikidata API synchronously for every entity, causing timeouts on episodes with many entities. The Wikidata Q-ID is not needed for embedding or RAG queries, so linking can be deferred.

## Changes

### Entity model (`episodes/models.py`)

Added `LinkingStatus` choices (`pending`, `linked`, `skipped`, `failed`) and `linking_status` field to `Entity`. Data migration sets existing entities with `wikidata_id` to `linked`.

### Resolver simplified (`episodes/resolver.py`)

- Removed `_fetch_wikidata_candidates()` function entirely
- Removed Wikidata candidates section from `_build_system_prompt()`
- "No existing entities" branch now creates all entities directly without LLM call
- "Existing entities" branch still uses LLM for deduplication but without Wikidata API calls

### Linking agent (new: `episodes/agents/linker.py`, `linker_tools.py`, `linker_deps.py`)

Pydantic AI agent that processes pending entities in batches:
1. Skips entities whose type has no Wikidata class Q-ID
2. Searches Wikidata for candidates via `search_wikidata` tool
3. Uses LLM to disambiguate and link via `link_entity` / `mark_failed` / `skip_entity` tools
4. Queues follow-up tasks for remaining entities

Triggered by `step_completed` signal when RESOLVING finishes, connected in `apps.py:ready()`.

### Management command (`episodes/management/commands/link_entities.py`)

```bash
uv run python manage.py link_entities              # Link all pending
uv run python manage.py link_entities --retry       # Reset failed → pending
uv run python manage.py link_entities --type musician
```

### Admin (`episodes/admin.py`)

Added `linking_status` to `EntityAdmin` display/filters. "Retry Wikidata linking" action resets selected entities to pending.

### Configuration

New settings: `RAGTIME_LINKING_AGENT_ENABLED` (default: true), `RAGTIME_LINKING_AGENT_API_KEY`, `RAGTIME_LINKING_AGENT_MODEL` (default: `openai:gpt-4.1-mini`), `RAGTIME_LINKING_AGENT_BATCH_SIZE` (default: 50).

## Key Parameters

| Parameter | Value | Rationale |
|---|---|---|
| `RAGTIME_LINKING_AGENT_BATCH_SIZE` | 50 | Balances LLM context usage and throughput |
| `RAGTIME_LINKING_AGENT_ENABLED` | true | On by default since it's non-blocking |
| Pydantic AI `request_limit` | 50 | Higher than recovery agent (30) since linking processes more entities |

## Verification

1. `uv run python manage.py check` — no issues
2. `uv run python manage.py test episodes` — all tests pass
3. Process an episode — resolve step completes without Wikidata calls
4. `uv run python manage.py link_entities` — links pending entities
5. Admin shows `linking_status` column with correct values

## Files Modified

| File | Change |
|---|---|
| `episodes/models.py` | Add `LinkingStatus` choices and `linking_status` field |
| `episodes/resolver.py` | Remove Wikidata API calls, simplify both resolution branches |
| `episodes/agents/linker.py` | New — Pydantic AI linking agent, signal handler |
| `episodes/agents/linker_deps.py` | New — `LinkingDeps` and `LinkingAgentResult` |
| `episodes/agents/linker_tools.py` | New — agent tools wrapping wikidata.py |
| `episodes/apps.py` | Connect `step_completed` signal to linking handler |
| `episodes/admin.py` | Add linking_status display, filters, retry action |
| `episodes/management/commands/link_entities.py` | New — CLI command |
| `episodes/migrations/0020_add_entity_linking_status.py` | Schema migration |
| `episodes/migrations/0021_set_linking_status_for_existing.py` | Data migration |
| `episodes/tests/test_resolve.py` | Remove Wikidata patches, rework affected tests |
| `episodes/tests/test_linker.py` | New — linking agent tests |
| `.env.sample` | Add `RAGTIME_LINKING_AGENT_*` variables |
| `core/management/commands/_configure_helpers.py` | Add Linking Agent to wizard |
| `README.md` | Update pipeline table, add linking agent note |
| `doc/README.md` | Rewrite resolve step, add Linking Agent section |
| `CHANGELOG.md` | Add entry |
