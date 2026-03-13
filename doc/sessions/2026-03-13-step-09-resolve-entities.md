# Session: Step 9 — Resolve Entities

**Date:** 2026-03-13

## Sessions

- `09ef4d53-d8b5-48a3-8fb8-bd017e1499ee` — Planning session
- Current session — Implementation

## Summary

Planned and implemented Step 9 of the RAGtime pipeline: LLM-based entity resolution that matches extracted entities against existing DB records using fuzzy matching, creates canonical `Entity` rows, and links them to episodes via `EntityMention`. Includes cross-language support, idempotent reprocessing, and full admin visibility.

## Conversation

## Session 1

### User
Asked to plan Step 9 — entity resolution. Provided detailed context about the goal: resolving raw extracted entities from `entities_json` against existing DB records to prevent duplicates, handling cross-language entity names, and creating canonical entity records.

### Assistant
Read the codebase: models, extractor, signals, admin, factory, settings, tests, entity types YAML, README, and documentation from Step 8. Explored the provider abstraction pattern and existing pipeline flow.

Entered plan mode and wrote a comprehensive implementation plan covering:
- Prerequisite: rename `DEDUPLICATING` → `RESOLVING` across codebase
- Data model: `Entity` (type + canonical name, unique constraint) and `EntityMention` (entity + episode + context)
- Resolution algorithm: skip LLM for first episode (no existing entities), use `structured_extract()` for fuzzy matching against existing entities
- Provider configuration: independent `RAGTIME_RESOLUTION_*` settings
- Signal dispatch, admin registration, and 11 tests

### User
Approved the plan and asked to implement it.

## Session 2

### User
Provided the finalized plan and asked to implement it. Referenced the planning session transcript for context.

### Assistant
Read all relevant source files to understand current state: models, extractor, signals, admin, factory, settings, test files, configure helpers, AGENTS.md, README, doc files, entity types YAML, and provider base classes. Checked existing migrations (6 total through `0006_episode_entities_json`).

Created feature branch `feature/step-09-resolve-entities` and implemented all changes in order:

1. **Renamed DEDUPLICATING → RESOLVING**: Updated `Episode.Status` choices in models, status transition in extractor, assertion in extract tests, pipeline table in README, and references in 4 doc files (step-08 plan/feature, step-01 plan/feature). Left session transcripts unmodified as historical records.

2. **Added Entity and EntityMention models**: `Entity` with `entity_type` (indexed), `name`, timestamps, and `UniqueConstraint(entity_type, name)`. `EntityMention` with FKs to Entity and Episode (both CASCADE), `context` field, and `UniqueConstraint(entity, episode, context)`.

3. **Settings and factory**: Added `RAGTIME_RESOLUTION_PROVIDER/API_KEY/MODEL` to settings. Added `get_resolution_provider()` to factory following existing pattern. Added "Resolution" subsystem to configure wizard.

4. **Resolver module** (`episodes/resolver.py`): Implemented `resolve_entities(episode_id)` with optimization to skip LLM call when no existing entities of a type exist. For types with existing entities, builds a system prompt listing candidates and calls `structured_extract()` with a response schema returning `matched_entity_id` (existing pk or null) and `canonical_name`. All writes wrapped in `transaction.atomic()`, with mention deletion for idempotent reprocessing.

5. **Signal dispatch**: Added `RESOLVING` clause to `queue_next_step` signal handler.

6. **Admin**: Registered `EntityAdmin` with mention count annotation (via `Count("mentions")`), type filter, name search, and `EntityMentionInlineForEntity`. Registered `EntityMentionAdmin` with context preview (truncated to 80 chars). Added `EntityMentionInlineForEpisode` to `EpisodeAdmin`. All entity views are read-only.

7. **Migration**: Generated `0007_alter_episode_status_entity_entitymention.py`. Added `RunSQL` to update existing `deduplicating` rows to `resolving` before the `AlterField`.

8. **Tests**: Created `test_resolve.py` with 10 tests: new entities (no LLM call), matching existing, mixed match/new, canonical name across languages, null types skipped, missing entities_json, wrong status, nonexistent episode, provider error, and idempotent reprocessing. Added signal test for RESOLVING dispatch.

First test run had 1 failure in `test_idempotent_reprocessing` — the second run triggered the LLM path (existing entity now in DB) but the mock wasn't configured for it. Fixed by configuring the mock to return a match result for the second run.

All 79 tests passing. Migration applied successfully. Django system checks clean.

9. **README**: Updated pipeline table status from `deduplicating` to `resolving`, added 3 `RAGTIME_RESOLUTION_*` env vars to Configuration section, added Features & Fixes entry.

10. **Documentation**: Created plan doc, feature doc, and session transcript.

### User
Asked whether the `extracted-entities-*.json` files in the project root were used as test fixtures. If not, use one with a proper name in the test fixtures directory.

### Assistant
Read the three JSON files (`extracted-entities-django-reinhardt.json`, `extracted-entities-ella-fitzgerald.json`, `extracted-entities-john-coltrane.json`). These are real extracted entities from German podcast episodes. Checked existing fixtures directory at `episodes/tests/fixtures/` which already had two Whisper transcript response fixtures.

Copied the Django Reinhardt file to `episodes/tests/fixtures/wdr-giant-steps-django-reinhardt-episode-extracted-entities.json` following the existing naming convention. Updated `test_resolve.py` to load `SAMPLE_ENTITIES` from the fixture via a `_load_fixture()` helper instead of the inline dict. Updated `test_resolve_new_entities` assertion from 4 to 59 entities (the fixture has 59 non-null entities across 11 types, with 3 null types: album, recording_session, label).

All 79 tests passing.

### User
Asked to update the session transcript and feature documentation.

### Assistant
Updated both files: added the fixture conversation turn to the session transcript, and added the fixture file to the Files Modified table in the feature doc.

### User
Asked whether there's a test covering re-processing of extracted entities.

### Assistant
Identified `test_idempotent_reprocessing` which covered the scenario but only with a single inline artist entity. Suggested strengthening it to use the full fixture (59 entities across 11 non-null types).

### User
Approved strengthening the test.

### Assistant
Rewrote `test_idempotent_reprocessing` to use `SAMPLE_ENTITIES` from the fixture. First run creates all 59 entities without LLM calls (no existing entities path). Second run uses a `side_effect` function on `structured_extract` that parses the entity type from the system prompt and returns matches for all existing entities. Assertions verify: 11 LLM calls (one per non-null type), 59 entities unchanged, 59 mentions recreated (old deleted, new created), and status advanced to EMBEDDING.

All 79 tests passing.

### User
Asked to update feature doc, session transcript, and create a PR.
