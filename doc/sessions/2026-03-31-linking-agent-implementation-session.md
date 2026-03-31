# Linking Agent — Implementation Session

**Date:** 2026-03-31

**Session ID:** unavailable — session UUID could not be recovered from Claude Code logs

## Summary

Implemented the decoupling of Wikidata entity linking from the pipeline resolve step into a background Pydantic AI linking agent. All code changes, migrations, tests, documentation, and configuration completed.

### User

(Plan approved — proceed with implementation)

### Assistant

Implemented all 9 steps from the plan:

**Step 1 — Entity model**: Added `LinkingStatus` TextChoices and `linking_status` field to `Entity`. Generated schema migration (`0020_add_entity_linking_status.py`) and data migration (`0021_set_linking_status_for_existing.py`) that sets `linked` for entities with existing `wikidata_id`.

**Step 2 — Simplified resolver**: Removed `_fetch_wikidata_candidates()` function entirely. Simplified `_build_system_prompt()` to remove Wikidata candidates section. Collapsed the "no existing entities" branch to create entities directly without LLM call. Removed unused `Chunk` import.

**Step 3 — Linking agent**: Created three new files:
- `episodes/agents/linker_deps.py` — `LinkingDeps` dataclass (tracks linked/failed/skipped counts) and `LinkingAgentResult` model
- `episodes/agents/linker_tools.py` — Four tools: `search_wikidata` (wraps `find_candidates`), `link_entity`, `mark_failed`, `skip_entity`
- `episodes/agents/linker.py` — Pydantic AI agent with system prompt specialized for jazz entity linking, `_build_model()` following recovery agent pattern, `run_linking_agent()` entry point with batch processing and auto-continuation, `handle_resolve_completed()` signal handler

**Step 4 — Signal wiring**: Updated `episodes/apps.py` to connect `step_completed` signal to `handle_resolve_completed`, with try/except for import errors (matching pattern used by recovery agent).

**Step 5 — Management command**: Created `episodes/management/commands/link_entities.py` with `--retry` (reset failed → pending) and `--type` (filter by entity type) options.

**Step 6 — Admin**: Added `linking_status` to `EntityAdmin.list_display` and `list_filter`. Added "Retry Wikidata linking" admin action that resets non-linked entities to pending and triggers the linker.

**Step 7 — Configuration**: Added `RAGTIME_LINKING_AGENT_*` variables to `.env.sample` and added Linking Agent section to configure wizard in `_configure_helpers.py`.

**Step 8 — Documentation**: Updated `README.md` pipeline table (resolve step description, linking agent note after table). Updated `doc/README.md` with rewritten resolve step (pure LLM resolution, no Wikidata), new Linking Agent section with status table, configuration, CLI commands, and file references. Updated Wikidata Cache section to reference linking instead of resolution.

**Step 9 — Tests**: Removed all 14 `@patch("episodes.resolver._fetch_wikidata_candidates")` decorators from `test_resolve.py`. Reworked 4 tests that specifically tested Wikidata integration: `test_wikidata_candidates_used_in_resolution` → `test_llm_returned_wikidata_id_saved_on_existing`, removed `test_wikidata_new_entities_with_candidates`, replaced `test_llm_omitted_name_fallback_new_entities` → `test_new_entities_created_directly_without_llm`, updated `test_noisy_wikidata_id_is_sanitized` to use existing entities for LLM path. Created `test_linker.py` with 9 tests covering linking status model, agent lifecycle (disabled, no pending, auto-skip), and signal handler (trigger on resolve, ignore other steps, no trigger when no pending, no trigger when disabled).

Verified: all imports compile, Django system checks pass (`manage.py check` — 0 issues). PostgreSQL not running locally so test suite could not be executed, but all files compile and import correctly.

### User

Create a PR with these changes

### Assistant

Created plan, feature, session, and changelog documentation. Committed all changes and created PR.
