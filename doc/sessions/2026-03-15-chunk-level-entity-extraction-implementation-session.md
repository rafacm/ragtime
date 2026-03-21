# Session: Chunk-level Entity Extraction — Implementation

**Date:** 2026-03-15
**Session ID:** 66396f5d-2329-4f7b-9cbe-ad108bbaa9cf

## Summary

Implemented chunk-level entity extraction and resolution, linking each entity mention to the specific chunk where it appeared.

## Conversation

### User

Implement the following plan:

# Chunk-level Entity Extraction & Resolution

## Context

The pipeline currently runs extraction on the full `episode.transcript` and stores results in `episode.entities_json`. Resolution then creates `EntityMention` records linked to episodes. Since chunking now runs **before** extraction, we have the opportunity to extract per-chunk, linking each entity mention to the specific chunk (and thus timestamp) where it appeared. This enables a future requirement: showing users which resolved entities appear in a given episode, with positional context.

## Pros & Cons of Chunk-level Extraction

| | Episode-level (current) | Chunk-level (proposed) |
|---|---|---|
| **LLM calls** | 1 per episode | ~40-60 per episode (one per chunk), but each uses ~150 words of input |
| **Cost** | Lower | Higher, though inputs are small so cost increase is moderate |
| **Entity provenance** | No link to where in the episode an entity was mentioned | Each mention tied to a specific chunk with timestamps |
| **Context quality** | Full transcript gives maximum disambiguation context | 150-word window may miss cross-chunk context; usually sufficient for named entities |
| **RAG alignment** | Entities disconnected from vector-embedded chunks | Entities and embeddings share the same unit (chunk) |
| **Code complexity** | Simpler | Aggregation step needed before resolution |
| **"Entities per episode" query** | Possible via EntityMention→Episode | Same, plus chunk-level detail (timestamps) for free |

**Verdict:** The provenance and RAG-alignment benefits justify the switch. Cost is manageable since chunk-level extraction inputs are tiny.

## Recommended Approach: Extract per-chunk, Resolve once per entity type

- **Extraction** runs per-chunk (provenance is the point).
- **Resolution** aggregates unique entity names across all chunks, then resolves once per entity type against the DB (same LLM call count as today for resolution).
- **EntityMention** records are created per (entity, chunk) pair.

### Flow

```
chunks ──► extract per chunk ──► aggregate unique names ──► resolve per type ──► create mentions per chunk
```

## Implementation

### 1. Model changes (`episodes/models.py`)

**Chunk** — add `entities_json = JSONField(blank=True, null=True)` to store raw extraction output per chunk.

**EntityMention** — add `chunk = ForeignKey(Chunk, CASCADE, related_name="entity_mentions")`. Keep `episode` FK (denormalized for query convenience). Replace unique constraint `(entity, episode, context)` with `(entity, chunk)`.

**Episode.entities_json** — stop writing to it. Keep the field for now (remove in a follow-up).

### 2. Migration

1. Add `Chunk.entities_json`
2. Add `EntityMention.chunk` (nullable initially)
3. Data migration: delete all existing EntityMention rows
4. Make `EntityMention.chunk` non-nullable
5. Drop old unique constraint, add new `(entity, chunk)`

### 3. Extractor changes (`episodes/extractor.py`)

- Validate chunks exist (instead of checking `episode.transcript`)
- Build system prompt and schema once (adjust wording: "transcript excerpt" instead of "transcript")
- Loop over chunks, call `provider.structured_extract(system_prompt, chunk.text, schema)`
- Store result in `chunk.entities_json`
- `bulk_update` all chunks in one DB call
- Transition to RESOLVING

### 4. Resolver changes (`episodes/resolver.py`)

**Phase A — Aggregate:** Collect `{type_key: {name: [(chunk, context), ...]}}` across all chunks.

**Phase B — Resolve:** For each entity type, same logic as today: if no existing entities, create directly; otherwise LLM fuzzy-match. Resolution uses unique names only (one call per type).

**Phase C — Create mentions:** For each (name, chunk, context) triple, create `EntityMention(entity=..., episode=..., chunk=..., context=...)`. Use `bulk_create(ignore_conflicts=True)`.

Handle "no entities in any chunk" as success (not failure) — transition to EMBEDDING.

### 5. Admin changes (`episodes/admin.py`)

Add `chunk` to `EntityMentionInlineForEpisode` and `EntityMentionInlineForEntity` readonly fields.

### 6. Tests

- **test_extract.py:** Create chunks, verify `chunk.entities_json` populated per chunk, N chunks → N LLM calls
- **test_resolve.py:** Create chunks with `entities_json`, verify EntityMention records have chunk FKs, test same entity in multiple chunks → multiple mentions, test aggregation (one resolution call with unique names)

## Critical files

- `episodes/models.py` — Chunk.entities_json, EntityMention.chunk
- `episodes/extractor.py` — per-chunk extraction loop
- `episodes/resolver.py` — aggregation + chunk-level mentions
- `episodes/admin.py` — chunk display on mentions
- `episodes/tests/test_extract.py` — updated tests
- `episodes/tests/test_resolve.py` — updated tests

## Verification

1. `uv run python manage.py makemigrations` — generates migration
2. `uv run python manage.py migrate` — applies cleanly
3. `uv run python manage.py test episodes` — all tests pass
4. Admin: EntityMention inlines show chunk column


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/d8df4186-a362-415c-9d05-bc068bbd5fd0.jsonl

### Assistant

I'll start by reading the key files to understand the current implementation.

Now let me read the existing tests.

Let me create a branch and start implementing.

Now let me implement all the changes. Starting with the model changes.

### 1. Model changes

### 2. Migration

I need to write the migration manually as the plan specifies: add chunk as nullable first, data migration to delete existing mentions, then make it non-nullable.

### 3. Extractor changes

### 4. Resolver changes

### 5. Admin changes

Also update the `EntityMentionAdmin` to include `chunk`:

### 6. Tests

Now let me read the fixture file to understand its structure before rewriting the resolver tests.

Now let me run the migration and tests.

All 102 tests pass. Let me also verify there are no pending migrations.

All clean. Now let me create the documentation per the project requirements. Let me first check what session ID to use and read the README for the pipeline section.

Now update the README pipeline descriptions to reflect chunk-level extraction:

Now let me read the CHANGELOG and existing docs to follow the format.

Now let me create the plan doc, feature doc, session transcripts, and changelog entry. Let me check existing session format.

Good, I have the format. Now let me create all the documentation files.

Now the session transcripts. Let me read the planning session transcript from the plan mode.

Let me check an existing session transcript format.

Good. Now let me create both session transcripts.

Now update the changelog.

Let me run the full test suite one more time to be sure.

All 102 tests pass. Here's a summary of what was implemented:

**Model changes:**
- `Chunk.entities_json` — stores raw extraction output per chunk
- `EntityMention.chunk` — FK linking each mention to its source chunk
- Unique constraint changed from `(entity, episode, context)` to `(entity, chunk)`

**Extractor (`episodes/extractor.py`):**
- Now validates chunks exist (not transcript)
- Loops over chunks, calling the LLM per chunk
- Stores results in `chunk.entities_json` via `bulk_update`

**Resolver (`episodes/resolver.py`):**
- Aggregates unique entity names across all chunks before resolving
- Creates `EntityMention` per (entity, chunk) pair
- "No entities in any chunk" is treated as success (not failure)

**Admin:** `chunk` column added to all EntityMention views.

**Tests:** Updated to create chunks, verify per-chunk extraction (N chunks → N LLM calls), same entity in multiple chunks → multiple mentions, and aggregation (one resolution call with unique names).

**Docs:** Plan, feature doc, session transcripts, changelog entry, and README updates all included.

### User

In the Django admin UI, when listing Entity Menions, I want to be able to click on an episode in the Episode column and go to the Episode detail page.

### Assistant

Done. The `episode` column in the EntityMention list view is now a clickable link (`episode_link`) that navigates to the Episode detail page. It uses `reverse("admin:episodes_episode_change", ...)` to generate the URL.

### User

Does it make sense to expose the Chunks also in the Django admin UI?

### Assistant

Yes — chunks are useful to inspect in admin for debugging extraction results and verifying timestamp boundaries. I'd suggest:

1. **Chunks are already visible as an inline on the Episode detail page** (the `ChunkInlineForEpisode` is already there).
2. Adding a **standalone `ChunkAdmin`** would let you browse/search/filter chunks independently — useful for checking `entities_json` per chunk after extraction.
3. The `EntityMention` inlines and list view could also link to chunks (same pattern as the `episode_link` we just added).

Want me to go ahead and register a `ChunkAdmin` (read-only, with `entities_json` visible and an `EntityMention` inline)?

### User

yes, go ahead

### Assistant

Now I'll add the `EntityMentionInlineForChunk` and `ChunkAdmin`, and make the chunk column in `EntityMentionAdmin` a clickable link too.

Now add the `ChunkAdmin` registration. I'll put it after the `EpisodeAdmin` class. Let me find a good insertion point.

Now let me also make the chunk column in `EntityMentionAdmin` a clickable link.

Also make the chunk inline on the Episode detail page link to the chunk detail:

All 102 tests pass. Here's what was added:

- **`ChunkAdmin`** — read-only, registered at `/admin/episodes/chunk/`. List view shows episode (linked), index, time range, text preview, and whether entities were extracted. Detail view has fieldsets for content, segments, and extracted entities JSON, plus an `EntityMention` inline when mentions exist.
- **Clickable links** — Episode and Chunk columns in the EntityMention list are now clickable links. The Chunk inline on the Episode detail page also has a "change link" to navigate to the Chunk detail.

### User

In the Chunk detail page, in the "Entity Mentions" section, we do not need to see the Episode column since that information is already at the top of the page.

### Assistant

Done. The `EntityMentionInlineForChunk` now explicitly lists only `entity`, `context`, and `created_at` — excluding `episode` and `chunk` since both are already clear from the parent page.

Let me check the current state and prepare the PR.

No commits yet — everything is uncommitted. Let me review the diff to understand the full scope, then commit and push.

PR requirements from CLAUDE.md: plan doc, feature doc, session transcripts (planning + implementation), and changelog entry. All are present. Let me commit and create the PR.

PR created: https://github.com/rafacm/ragtime/pull/47

### User

Wait 10 minutes and then execute the /pr-review-process command

### Assistant

I'll wait 10 minutes and then process the PR review.

Here are the 5 review comments from **Copilot**:

---

### 1. Silent context loss with `ignore_conflicts` in `bulk_create`
**File:** `episodes/resolver.py:139-150`
**Severity:** Medium
**Issue:** `bulk_create(ignore_conflicts=True)` silently drops duplicate `(entity, chunk)` pairs. If the extractor returns the same entity name multiple times within a chunk (with different context strings), one context is lost non-deterministically.
**Reviewer's fix:** De-duplicate `names_dict[name]` by `chunk_id` (choosing a deterministic context like first non-empty), then insert without `ignore_conflicts` so unexpected duplicates surface during development.
**My suggested action:** Agree — de-duplicate by chunk in `_aggregate_entities_from_chunks()` (keep first context per chunk), then remove `ignore_conflicts`. This is a real data-loss risk.

---

### 2. High-cardinality `list_filter` on `ChunkAdmin`
**File:** `episodes/admin.py:274`
**Severity:** Low
**Issue:** `list_filter = ("episode__title",)` produces one filter entry per unique episode title, making the sidebar huge and slow.
**Reviewer's fix:** Use `("episode",)` (FK filter) or a custom `SimpleListFilter`.
**My suggested action:** Agree — switch to `list_filter = ("episode",)`. Simple fix, valid usability concern.

---

### 3. Redundant inner import of `Chunk` in `extractor.py`
**File:** `episodes/extractor.py:121-122`
**Severity:** Low (code hygiene)
**Issue:** `from .models import Chunk` inside the function body is redundant since the module already imports from `.models` at the top.
**Reviewer's fix:** Move `Chunk` to the top-level import.
**My suggested action:** Agree — add `Chunk` to the existing top-level import. Trivial fix.

---

### 4. Missing `EntityMention` cleanup in early-return path
**File:** `episodes/resolver.py:103-105`
**Severity:** Medium
**Issue:** When there are no chunks or no entities in any chunk, the function transitions to EMBEDDING without deleting existing `EntityMention` rows. This breaks idempotent reprocessing — stale mentions survive from a previous run.
**Reviewer's fix:** Delete `EntityMention.objects.filter(episode=episode)` before the early return.
**My suggested action:** Agree — add the delete before the early return. This is a real correctness bug for reprocessing.

---

### 5. Per-name DB round-trips in "no existing entities" path
**File:** `episodes/resolver.py:127-138`
**Severity:** Low (performance)
**Issue:** The loop does one `Entity.objects.create()` + one `bulk_create()` per unique name. For episodes with many entities this means many DB round-trips.
**Reviewer's fix:** Batch entity creation and collect all mentions, then do a single `bulk_create` per entity type.
**My suggested action:** Partially agree — batching mentions is worthwhile, but `Entity.objects.create()` per name is needed to get back PKs for the mention FKs (SQLite doesn't support `bulk_create` returning IDs). We can at least batch all mentions into one `bulk_create` per type. Low priority since entity counts per type are small (~5-15).

---

Want me to implement these fixes?

No response requested.

Let me read the current state of the files I need to modify.

Now I'll implement all 5 fixes.

**Fix 1 & 5: De-duplicate by chunk in aggregation, remove `ignore_conflicts`, batch mentions per type**

**Fix 3: Move `Chunk` import to module scope**

**Fix 4: Delete stale mentions in early-return path**

**Fix 2: Change `list_filter` from `episode__title` to `episode`**

Now fix the resolver — de-duplicate by chunk in aggregation, delete mentions on early return, batch mentions, remove `ignore_conflicts`:

Now fix the early-return path to delete stale mentions:

Now batch mentions per type and remove `ignore_conflicts`:

Now fix the admin `list_filter`:

Now run tests:

All 102 tests pass. Now let me reply to each PR comment and update the session transcript.

All replies posted. Now update the implementation session transcript and commit.

Now commit and push:

All 5 review comments addressed, replied to, and pushed:

1. **De-duplicate by chunk** — `_aggregate_entities_from_chunks()` now keeps first context per `(name, chunk)`, removed `ignore_conflicts`
2. **`list_filter`** — changed from `episode__title` to `episode` FK
3. **Redundant import** — `Chunk` moved to top-level import in `extractor.py`
4. **Stale mentions** — early-return path now deletes existing `EntityMention` rows
5. **Batch creates** — all mentions per entity type collected into single `bulk_create`

Session transcript updated with all review comments and fixes.

### User

Set the resolved comments as resolved.

### Assistant

All 5 review threads resolved.

No response requested.

No response requested.

### User

Wait 10 minutes and then execute the /pr-review-process command

### Assistant

Now let me check which threads are still unresolved:

All 5 review threads are already **resolved** from the previous round. There are no new or open review comments on PR #47. Nothing to action.

Three new unresolved review comments from **Copilot**:

---

### 1. False positive "has entities" check allows unnecessary resolution path
**Reviewer:** Copilot
**File:** `episodes/resolver.py:113`
**Severity:** Medium
**Issue:** `has_any_entities = any(chunk.entities_json for chunk in chunks)` treats a dict with all-null values (e.g. `{"artist": null, "band": null, ...}`) as truthy. This means the code enters the resolution path, calls `get_resolution_provider()`, and could fail on missing provider config — even though there's nothing to resolve.
**Reviewer's fix:** Compute `aggregated` first and early-return when it's empty, or change the predicate to check for at least one non-empty entity list.
**My suggested action:** Agree. Move the `_aggregate_entities_from_chunks()` call before the early-return check and use `if not aggregated:` instead. This is cleaner and handles the all-null case correctly.

---

### 2. Stale `episode.entities_json` after extraction
**Reviewer:** Copilot
**File:** `episodes/extractor.py:125`
**Severity:** Low
**Issue:** `extract_entities()` no longer writes to `episode.entities_json`, so reprocessing leaves a stale value from older runs. The admin still conditionally shows the "Entities" fieldset based on `obj.entities_json`, which is misleading.
**Reviewer's fix:** Clear `episode.entities_json = None` on successful extraction, or remove the Episode-level fieldset.
**My suggested action:** Agree. Clear `episode.entities_json = None` on successful extraction so stale data doesn't persist. The admin fieldset will then naturally hide itself.

---

### 3. Stale documentation — mentions `ignore_conflicts` after it was removed
**Reviewer:** Copilot
**File:** `doc/sessions/2026-03-15-chunk-level-entity-extraction-implementation-session.md:35`
**Severity:** Low (docs)
**Issue:** The session transcript still says `bulk_create(ignore_conflicts=True)` but the code no longer uses `ignore_conflicts` after the first review round.
**Reviewer's fix:** Update the bullet to reflect current implementation.
**My suggested action:** Agree. Update the line to say `bulk_create` with de-duplication in `_aggregate_entities_from_chunks()`.

---

Want me to implement these fixes?

Let me read the current state of the files I need to modify.

Now implement all three fixes:

**Fix 1: Move aggregation before early-return check in resolver**

**Fix 2: Clear `episode.entities_json` on successful extraction**

**Fix 3: Update stale documentation**

Now update the session transcript with these review fixes, and update the existing test for the all-null case:

Let me check the existing null types test to see if it already covers the all-null dict case:

Good — `test_null_types_skipped` already covers the all-null dict case. With the new code, this goes through the `if not aggregated:` early return instead of entering the resolution path. Let me also verify `get_resolution_provider` is not called in that test:

Now let me also verify the extractor test still passes with the `entities_json = None` change:

All 102 tests pass. Now update the session transcript and reply to the comments.

Now reply to each comment and resolve:

That replied to the wrong thread. Let me get the correct comment IDs for the second round:

Now reply to the correct comment IDs:

Now resolve all three threads:

Now commit and push:

All 3 second-round review comments addressed, replied to, and resolved:

1. **False positive "has entities" check** — moved `_aggregate_entities_from_chunks()` before early-return, using `if not aggregated:` instead of truthy `entities_json` check. Added `mock_factory.assert_not_called()` assertion.
2. **Stale `episode.entities_json`** — cleared to `None` on successful extraction.
3. **Stale docs** — updated session transcript to reflect current `bulk_create` without `ignore_conflicts`.

Session transcript updated. All 102 tests pass.

### User

When trying to delete an Episode via the Django admin I get this error: 
Cannot delete episodes
Deleting the selected episodes would result in deleting related objects, but your account doesn't have permission to delete the following types of objects:

chunk

### Assistant

The `ChunkAdmin` has `has_delete_permission` returning `False`, which prevents cascade deletion of chunks when deleting an episode through admin.

The fix is to remove the `has_delete_permission` override on `ChunkAdmin` so Django allows cascade deletes when an episode is deleted. Chunks shouldn't be directly deletable from their own list view, but they need to be deletable as part of a cascade. Unfortunately, Django admin's `has_delete_permission` controls both — so we need to allow it.

Removed `has_delete_permission = False` from `ChunkAdmin`. Django needs delete permission on related models for cascade deletes to work through the admin. Episodes can now be deleted, and chunks will cascade as expected.

### User

Update the PR with this change

### Assistant

Pushed to PR #47.

On `main`, pulled latest — PR #47 has been merged. 13 files updated with the chunk-level extraction feature.
