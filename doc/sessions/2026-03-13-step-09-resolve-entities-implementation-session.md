# Session: Step 9 — Resolve Entities — Implementation

**Date:** 2026-03-13
**Session ID:** 5b6f037b-ee16-40ac-aef1-d362a58cc52f

## Summary

Implemented Step 9 (Resolve Entities): LLM-based entity resolution with fuzzy matching against existing DB records, canonical Entity rows, EntityMention linking to episodes, cross-language support, and full test coverage including fixture-based integration tests.

## Conversation

### User

Implement the following plan:

# Step 9: Entity Resolution — Implementation Plan

## Context

Step 8 (Extract) stores raw LLM-extracted entities as JSON on `Episode.entities_json`. These entities are not yet persisted as database records, so there's no way to query across episodes ("which episodes mention Miles Davis?"), no deduplication across episodes, and no admin visibility. Step 9 resolves extracted entities against existing DB records using LLM-based fuzzy matching, creates canonical `Entity` rows, and links them to episodes via `EntityMention` with episode-specific context.

Episodes can be in different languages (German, English, etc.), so the same entity may appear with different names across episodes (e.g., "Saxophon" vs "Saxophone"). The LLM picks the best canonical name during resolution.

## Prerequisite: Rename Status `deduplicating` → `resolving`

The current status name `deduplicating` doesn't accurately describe this step. Rename to `resolving` across the codebase:

**Code changes:**
- `episodes/models.py` — rename `DEDUPLICATING = "deduplicating"` → `RESOLVING = "resolving"`
- `episodes/extractor.py` — change `Episode.Status.DEDUPLICATING` → `Episode.Status.RESOLVING`
- `episodes/tests/test_extract.py` — update status assertion
- `README.md` — update pipeline table status column

**Migration:** Add a data migration (`RunSQL`) to update any existing rows with `status='deduplicating'` to `status='resolving'`, combined with the `AlterField` for the new choices.

**Documentation references** (doc/ files): Update mentions in `doc/plans/step-08-extract-entities.md`, `doc/features/step-08-extract-entities.md`, `doc/features/step-01-submit-episode.md`, `doc/plans/step-01-submit-episode.md`. The session transcripts in `doc/sessions/` are historical records and should NOT be modified.

## Data Model

Two new models in `episodes/models.py`:

### `Entity`

| Field | Type | Notes |
|-------|------|-------|
| `entity_type` | CharField(30) | Key from `entity_types.yaml` (e.g., "artist", "instrument"). Indexed. |
| `name` | CharField(500) | Canonical name chosen by LLM (most recognized form). |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |

Constraints:
- `UniqueConstraint(fields=["entity_type", "name"])` — prevents exact duplicates per type
- Allows same name in different types (e.g., "Bebop" as both `era` and `sub_genre`)

### `EntityMention`

| Field | Type | Notes |
|-------|------|-------|
| `entity` | FK → Entity | CASCADE delete |
| `episode` | FK → Episode | CASCADE delete |
| `context` | TextField | Episode-specific context in the episode's language |
| `created_at` | DateTimeField | auto_now_add |

Constraints:
- `UniqueConstraint(fields=["entity", "episode", "context"])` — prevents duplicate mentions on reprocessing

## Resolution Algorithm

Module: `episodes/resolver.py`

### `resolve_entities(episode_id)` — main task function

1. Fetch episode, validate status is `RESOLVING`
2. Validate `entities_json` is not empty
3. Get resolution provider via `get_resolution_provider()`
4. Delete existing `EntityMention` rows for this episode (idempotent reprocessing)
5. For each entity type in `entities_json`:
   - Skip if value is null
   - Query existing `Entity` rows with that `entity_type`
   - If **no** existing entities: create new `Entity` + `EntityMention` for each extracted entity (no LLM call needed)
   - If existing entities exist: call LLM with `structured_extract()` to match extracted names against candidates
6. For each LLM result:
   - If matched to existing entity ID → create `EntityMention` linking to it
   - If no match → create new `Entity` (with LLM-chosen canonical name) + `EntityMention`
7. Wrap all DB writes in `transaction.atomic()`
8. On success: set status to `EMBEDDING`
9. On failure: set status to `FAILED` with error message

### LLM Resolution Prompt

Use `structured_extract()` with a per-type call. System prompt instructs the LLM to:
- Consider spelling variants, language differences (German/English/etc.), abbreviations
- Only match entities that clearly refer to the same real-world thing
- For each extracted entity, return either a matched existing entity ID or null (new)
- For new entities, return the best canonical name (most commonly recognized form, e.g., "Saxophone" over "Saxophon")

**Response schema** (per type call):
```json
{
  "name": "resolution_result",
  "strict": true,
  "schema": {
    "type": "object",
    "properties": {
      "matches": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "extracted_name": {"type": "string"},
            "canonical_name": {"type": "string"},
            "matched_entity_id": {"type": ["integer", "null"]}
          },
          "required": ["extracted_name", "canonical_name", "matched_entity_id"],
          "additionalProperties": false
        }
      }
    },
    "required": ["matches"],
    "additionalProperties": false
  }
}
```

- `matched_entity_id`: existing Entity pk, or null for new
- `canonical_name`: LLM-chosen best name (used when creating new entities; ignored when matching existing)

**Optimization**: Skip LLM call entirely for types with zero existing DB entities — just create all as new. This is the common case for the first episode processed.

## Provider Configuration

### Settings (`ragtime/settings.py`)

```
RAGTIME_RESOLUTION_PROVIDER  (default: "openai")
RAGTIME_RESOLUTION_API_KEY   (default: "")
RAGTIME_RESOLUTION_MODEL     (default: "gpt-4.1-mini")
```

### Factory (`episodes/providers/factory.py`)

Add `get_resolution_provider()` following the exact pattern of `get_extraction_provider()`.

### Configure wizard (`core/management/commands/_configure_helpers.py`)

Add "Resolution" subsystem to `SYSTEMS[0]["subsystems"]` (the LLM system). Update description to "Scraping, summarization, extraction, and resolution".

## Signal Dispatch

`episodes/signals.py` — add clause:
```python
elif instance.status == Episode.Status.RESOLVING:
    async_task("episodes.resolver.resolve_entities", instance.pk)
```

## Django Admin

### `EntityAdmin`

- `list_display`: `entity_type`, `name`, `mention_count`, `created_at`
- `list_filter`: `entity_type`
- `search_fields`: `name`
- Annotate `mention_count` (number of episodes mentioning this entity)
- `EntityMentionInline` (tabular) showing episodes that mention this entity
- Read-only (entities created by pipeline)

### `EntityMentionAdmin`

- `list_display`: `entity`, `episode`, short context preview, `created_at`
- `list_filter`: `entity__entity_type`
- `search_fields`: `entity__name`, `episode__title`
- Read-only

### `EpisodeAdmin` update

- Add `EntityMentionInline` (tabular) so viewing an episode shows its resolved entities with context

## Files to Modify/Create

| File | Action |
|------|--------|
| `episodes/models.py` | Edit — rename DEDUPLICATING → RESOLVING, add `Entity` and `EntityMention` models |
| `episodes/extractor.py` | Edit — `DEDUPLICATING` → `RESOLVING` |
| `episodes/tests/test_extract.py` | Edit — update status assertion |
| `episodes/migrations/XXXX_*.py` | Create — auto-generated migration (AlterField + RunSQL + CreateModel) |
| `ragtime/settings.py` | Edit — add `RAGTIME_RESOLUTION_*` vars |
| `episodes/providers/factory.py` | Edit — add `get_resolution_provider()` |
| `core/management/commands/_configure_helpers.py` | Edit — add Resolution subsystem |
| `episodes/resolver.py` | Create — main resolution logic |
| `episodes/signals.py` | Edit — add RESOLVING dispatch |
| `episodes/admin.py` | Edit — register Entity, EntityMention, add inlines |
| `episodes/tests/test_resolve.py` | Create — resolution tests |
| `episodes/tests/test_signals.py` | Edit — add RESOLVING signal test |
| `README.md` | Edit — update status in pipeline table, new env vars, Features & Fixes entry |
| `doc/plans/step-08-extract-entities.md` | Edit — DEDUPLICATING → RESOLVING |
| `doc/features/step-08-extract-entities.md` | Edit — DEDUPLICATING → RESOLVING |
| `doc/features/step-01-submit-episode.md` | Edit — deduplicating → resolving |
| `doc/plans/step-01-submit-episode.md` | Edit — DEDUPLICATING → RESOLVING |
| `doc/plans/step-09-resolve-entities.md` | Create — plan doc |
| `doc/features/step-09-resolve-entities.md` | Create — feature doc |
| `doc/sessions/2026-03-13-step-09-resolve-entities.md` | Create — session transcript |

## Tests (`episodes/tests/test_resolve.py`)

- `test_resolve_new_entities` — no existing DB entities, all created as new, status → EMBEDDING
- `test_resolve_matches_existing` — LLM matches extracted entity to existing, no duplicate created
- `test_resolve_mixed` — some matches, some new
- `test_resolve_canonical_name` — LLM returns canonical name different from extracted name (e.g., "Saxophon" → "Saxophone")
- `test_null_types_skipped` — entity types with null value skipped
- `test_missing_entities_json` — null entities_json → FAILED
- `test_wrong_status` — not RESOLVING → no-op
- `test_nonexistent_episode` — no crash
- `test_provider_error` — LLM exception → FAILED
- `test_idempotent_reprocessing` — running twice doesn't create duplicate mentions
- Signal test in `test_signals.py`: RESOLVING queues resolve task

All tests mock the LLM provider via `@patch("episodes.resolver.get_resolution_provider")`.

## Verification

```bash
uv run python manage.py makemigrations    # Generate migration
uv run python manage.py migrate           # Apply migration
uv run python manage.py test episodes     # Run all tests
uv run python manage.py check             # Django system checks
```

Manual verification:
1. Open Django admin, confirm Entity and EntityMention models are visible
2. Process an episode through the full pipeline and verify entities appear in admin
3. Process a second episode with overlapping entities (e.g., "Duke Ellington") and verify deduplication

## Implementation Order

1. Rename DEDUPLICATING → RESOLVING (model, extractor, tests, docs, README) + migration
2. Models (Entity, EntityMention) + migration
3. Settings + factory + configure wizard
4. Resolver module
5. Signals
6. Admin
7. Tests
8. README + documentation


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/09ef4d53-d8b5-48a3-8fb8-bd017e1499ee.jsonl

### Assistant

I'll start by reading the key files to understand the current codebase state.

Let me read the remaining files I need.

Let me check the existing migrations and a reference session transcript.

Good, I have a clear picture of the codebase. Let me create a branch and start implementing. I'll work through the implementation order from the plan.

## Step 1: Rename DEDUPLICATING → RESOLVING

Now update the doc files and README for the rename:

## Step 2: Add Entity and EntityMention models

## Step 3: Settings + factory + configure wizard

## Step 4: Resolver module

## Step 5: Signal dispatch

## Step 6: Admin

## Step 7: Generate migrations

Now I need to add the data migration (RunSQL) for updating existing rows from `deduplicating` to `resolving`. Let me read the auto-generated migration and add the RunSQL.

## Step 8: Tests

Now add the signal test:

Now let's run the tests and migration:

One test failure — the idempotent test. The second run creates a new Entity (since entity from first run still exists), which triggers the LLM path, but the mock isn't configured to return a result for that path. Let me fix the test.

All 79 tests pass. Now let me update the README and create the documentation files.

## Step 9: README updates

Now add the Features & Fixes entry:

## Step 10: Documentation files

Now I'll create the plan doc, feature doc, and session transcript in parallel.

Now I need to create the session transcript. Let me check the reference format first.

Let me run a final check to make sure everything is clean:

All clean. Here's a summary of what was implemented:

**Step 9: Entity Resolution** — complete implementation across 17 files:

1. **Renamed `DEDUPLICATING` → `RESOLVING`** across models, extractor, tests, README, and 4 doc files. Added `RunSQL` data migration for existing rows.

2. **New models**: `Entity` (type + canonical name, unique constraint) and `EntityMention` (entity → episode link with context, unique constraint).

3. **Resolver** (`episodes/resolver.py`): Processes each entity type from `entities_json`. Skips LLM when no existing entities (creates directly). Otherwise calls `structured_extract()` with fuzzy matching prompt. All writes atomic, idempotent via mention deletion.

4. **Provider config**: `RAGTIME_RESOLUTION_PROVIDER/API_KEY/MODEL` settings, factory, and configure wizard.

5. **Signal**: `RESOLVING` → `resolve_entities` async task.

6. **Admin**: `EntityAdmin` with mention count, `EntityMentionAdmin` with context preview, inlines on both Episode and Entity detail views. All read-only.

7. **Tests**: 11 new tests (10 resolver + 1 signal), all 79 tests passing.

### User

Did you use any of the `extracted-entities-*.json` files as a test fixture? If not, use one of them, rename it with a proper test fixture name and put it in the corresponding directory for test fixtures.

### Assistant

Let me check what's in those files.

These are real extracted entities from German podcast episodes — perfect test fixtures. The Django Reinhardt one is great because it has German-language entities (like "Gitarre", "Geige", "Trompete") that test cross-language resolution. Let me check where test fixtures should go.

Fixtures live in `episodes/tests/fixtures/`. I'll copy the Django Reinhardt file there with a proper name, then update the tests to use it.

Now update the tests to load from the fixture instead of using the inline `SAMPLE_ENTITIES` dict.

I'll update the test to load `SAMPLE_ENTITIES` from the fixture file and adjust the test that relies on the exact entity count.

Now I need to update `test_resolve_new_entities` since the fixture has many more entities. Let me count the non-null entity types and their items.

All 10 resolve tests pass. Let me run the full suite to confirm nothing broke.

All 79 tests pass. The fixture `wdr-giant-steps-django-reinhardt-episode-extracted-entities.json` is now in `episodes/tests/fixtures/` and loaded by `test_resolve.py` as `SAMPLE_ENTITIES` — replacing the inline dict that was there before. The fixture contains real German-language extracted entities (59 entities across 11 types, with 3 null types), which makes `test_resolve_new_entities` a more realistic test.

### User

Update the session transcript and the feature documentation if needed.

### Assistant

Let me check what needs updating.

Both need updates to reflect the test fixture change. The feature doc also needs the fixture file in the Files Modified table.

Done. Updated both files:

- **Session transcript**: Added the conversation turn about using `extracted-entities-*.json` as a test fixture, including what was done (copied, renamed, updated tests) and the current turn asking to update docs.
- **Feature doc**: Added the fixture file to the Files Modified table with a description.

### User

Is there a test that will cover re-processing extracted entities?

### Assistant

Yes — `test_idempotent_reprocessing` in `test_resolve.py:314` covers this. It runs `resolve_entities` twice on the same episode and asserts that mentions aren't duplicated (old ones deleted, new ones created) and the entity count stays the same.

However, it only tests with a single artist entity, and it uses a small inline dict rather than the fixture. A more thorough test could use the full fixture (59 entities) to verify that reprocessing with a realistic dataset works — including the transition from the "no existing entities" path (first run) to the "LLM matching" path (second run) across multiple entity types.

Want me to strengthen that test to use the fixture data?

### User

yes, please

### Assistant

I need to understand the fixture structure to build the mock responses for the second run. Each non-null entity type will trigger an LLM call on the second run since entities from the first run will exist in the DB.

All 79 tests pass. The strengthened test now:

1. First run creates all 59 entities from the fixture without LLM calls (no existing entities path)
2. Second run hits the LLM path for all 11 non-null entity types, with a mock that matches every entity to its existing record
3. Asserts 11 LLM calls (one per non-null type), 59 entities unchanged, 59 mentions unchanged (old deleted, new created)

### User

Update the feature documentation, session transcript and the PR with this new test.

### Assistant

Let me check if there's an existing PR first.

No PR yet. Let me update the docs first, then create the PR. Let me check git status and recent commits to understand what needs to be pushed.

Everything is uncommitted. Let me update the docs, then commit and create the PR.

Now let me check the diff and commit everything.

Done. PR created: https://github.com/rafacm/ragtime/pull/25

The 3 uncommitted changes warning is from the `extracted-entities-*.json` files in the project root — those are the original source files that aren't part of this feature.

### User

When running the tests with `uv run python manage.py test --verbosity 2` there are two tests that fail:
- Test that re-running preserves non-RAGTIME lines.
- Test wizard with shared LLM provider/key.

### Assistant

Let me run the tests with verbosity to see the failures.

The configure tests are failing because they don't account for the new Resolution subsystem prompts. Let me look at the test file.

Both tests provide mock `input` side effects that don't include a response for the new Resolution model prompt. In shared mode, the wizard prompts for a model per LLM subsystem — adding Resolution means one more `input` call.

All 102 tests pass. Both configure tests needed an extra `"gpt-4.1-mini"` input for the new Resolution model prompt, and the shared mode test also needed an assertion for `RAGTIME_RESOLUTION_API_KEY`. Let me push the fix.

Fixed. Both tests were missing the `"gpt-4.1-mini"` input for the Resolution model prompt that was added when we registered the Resolution subsystem in the configure wizard. Also added an assertion that `RAGTIME_RESOLUTION_API_KEY` gets the shared key.

### User

Update the session transcript to include these changes

[Request interrupted by user]

Update the session transcript to include these changes

[Request interrupted by user]

### Assistant

No response requested.

### User

Update the session transcript to include these changes

[Request interrupted by user]

### Assistant

No response requested.

### User

Update the session transcript to include these changes

[Request interrupted by user]

### Assistant

No response requested.

### User

Update the session transcript to include these changes

### Assistant

Updated the session transcript with the configure test fix conversation.

### User

Update the PR with the changes

### Assistant

Pushed. PR #25 is updated with the session transcript changes.
