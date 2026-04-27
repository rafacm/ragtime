# MusicBrainz Resolution — Implementation Session

**Date:** 2026-04-27

**Session ID:** 2a9d5c4e-1263-4d89-a97a-973e9193a72a

## Summary

Implemented the approved plan in 9 sequential tasks: schema additions + migration, YAML mapping, env vars + configure wizard, MusicBrainz module + tests, resolver refactor + tests, enrichment workflow + queue + tests + management command, episode pipeline queue + dedup, slim Qdrant payload + search-time Postgres hydration + 409-tolerant `ensure_collection`, and a final test-suite green pass. Then wrote documentation, ran cutover sanity checks, and created the PR.

Mid-implementation, the previous worktree's directory was removed by the runtime (`/Users/rafa/Develop/projects/ragtime/.claude/worktrees/feature-episodes-rail-and-player`), forcing a session restart from the main repo. The user typed "You are now on the main branch" at restart; from there I created a fresh worktree (`feature-musicbrainz-resolution`) and continued.

The full test suite goes from 261 baseline tests to 322 passing tests (61 new tests for MB / enrichment / slim-payload hydration / queue dedup).

## Detailed conversation

### User

> Carry out the remaining TODOs and then create a PR.

### Assistant (implementation begins, after plan approval and worktree creation)

Set up nine implementation tasks via TaskCreate, with `blockedBy` dependencies:

1. Add data model fields & migration
2. Map MusicBrainz tables in entity types YAML
3. Add MB & concurrency env vars
4. Implement `episodes/musicbrainz.py`
5. Refactor `resolver.py` — MB-first, race-safe
6. Implement enrichment workflow + queue
7. Episode pipeline queue & dedup
8. Slim Qdrant payload + Postgres hydration
9. Run full test suite & fix regressions

Then started executing.

**Task 1 — Schema.** Added `Episode.Status.QUEUED` between PENDING and SCRAPING, four new Entity fields (`musicbrainz_id`, `wikidata_status` enum, `wikidata_attempts`, `wikidata_last_attempted_at`), two new `EntityType` fields (`musicbrainz_table`, `musicbrainz_filter`), and a partial unique constraint on `ProcessingRun(episode_id) WHERE status='running'`. Generated migration `0020_*`. `manage.py check` clean.

**Task 2 — YAML.** Updated `episodes/initial_entity_types.yaml` with `musicbrainz_table` + `musicbrainz_filter` per type (8 mapped types, 6 empty). Also updated `load_entity_types` management command to populate the new fields.

**Task 3 — Settings.** Added `RAGTIME_MUSICBRAINZ_DB_*` env vars (defaults inherit from `RAGTIME_DB_*` so users with MB in the same Postgres get sane defaults), `RAGTIME_MUSICBRAINZ_SCHEMA=musicbrainz`, and `RAGTIME_EPISODE_CONCURRENCY=4`. Updated `.env.sample`. Restructured `_configure_helpers.SYSTEMS` to add a "MusicBrainz" section (DB connection + schema sub-system) and a "Pipeline" section (concurrency).

**Task 4 — MB module.** Wrote `episodes/musicbrainz.py` with:

- `psycopg_pool.ConnectionPool` (lazy, `min_size=1, max_size=8`, `autocommit=True`, `search_path` set via `options`).
- `find_candidates(name, entity_type, *, limit=10)` — Common Table Expression (`WITH name_matches AS …`) that UNIONs main-table exact-name matches (rank=0) with alias-table matches (rank=1), joins back, applies the optional type filter (`artist_type`, `area_type`, …), groups, and orders by best rank then name. Branches per `cfg["type_table"]` presence to avoid referencing `t.name` when no type table is joined.
- `get_wikidata_qid(mbid, entity_type)` — joins `l_<entity>_url` → `url` filtered by URL regex `^https?://(www\.)?wikidata\.org/(wiki|entity)/Q[0-9]+`, parses the Q-ID with `_WIKIDATA_QID_RE`.

Added `pyproject.toml` dependency `psycopg_pool>=3.2,<4` (psycopg base was already present), ran `uv sync`.

Wrote 12 tests in `episodes/tests/test_musicbrainz.py` using `SimpleTestCase` (no DB required) and a `_fake_pool` helper that mocks the `with pool.connection() as conn / with conn.cursor() as cur` context-manager chain.

First draft used a single SQL template with conditional joins, and after a re-read I refactored to two clean per-branch templates (with-type-table vs. without) for readability. All 12 tests pass.

**Task 5 — Resolver.** Wrote a stub `episodes/enrichment.py` first so the resolver's lazy import works. Then rewrote `episodes/resolver.py`:

- `_sanitize_qid` becomes `_sanitize_mbid` (UUID regex). Lowercased on extract.
- `RESOLUTION_RESPONSE_SCHEMA` field renamed `wikidata_id` → `musicbrainz_id`.
- `_fetch_wikidata_candidates` becomes `_fetch_musicbrainz_candidates`; calls `episodes.musicbrainz.find_candidates`.
- `_build_system_prompt` shows `[mb:<uuid>]` next to existing entities and "MusicBrainz candidates" instead of "Wikidata candidates".
- `_acquire_name_locks(entity_type_id, names)` issues `pg_advisory_xact_lock(hashtextextended('<type_id>:<name>', 0))` for each unique name, sorted to enforce global ordering. Locks release at txn end.
- `_get_or_create_entity` wraps `Entity.objects.get_or_create` with `IntegrityError` fallback (defense-in-depth) and updates `musicbrainz_id` post-create if the LLM provided one.
- All `Entity.objects.create(...)` call sites replaced with `_get_or_create_entity`.
- Foreground never imports `episodes.wikidata`.
- After commit (outside `transaction.atomic`), calls `_enqueue_enrichment(new_entity_ids)` which lazy-imports `episodes.enrichment.enqueue_entities`.

Rewrote `episodes/tests/test_resolve.py` (28 tests). Mock target moved from `episodes.resolver._fetch_wikidata_candidates` to `episodes.resolver._fetch_musicbrainz_candidates`; LLM responses use `musicbrainz_id`; tests checking foreground wikidata_id assignment are replaced with their `musicbrainz_id` analogues. Added a new test `test_foreground_does_not_call_wikidata` that patches `episodes.wikidata.find_candidates` and asserts `not_called`. `setUp` patches `episodes.resolver._enqueue_enrichment` so tests don't try to enqueue real DBOS workflows. All 28 tests pass.

**Task 6 — Enrichment workflow.** Wrote `episodes/enrichment.py` with `enrich_entity_wikidata_impl` (plain function, testable without DBOS runtime) and a thin `@DBOS.workflow()` wrapper. First draft put the body inside `@DBOS.workflow()`, which raised `DBOSException: Function enrich_entity_wikidata invoked before DBOS initialized` from tests. Refactored: business logic in plain functions, DBOS decorator wraps a one-line call.

Strategy:

```python
def enrich_entity_wikidata_impl(entity_id):
    entity = _fetch_entity(entity_id)
    if entity is None or entity.wikidata_id:
        return  # already enriched (idempotent)
    if entity.wikidata_attempts >= MAX_ATTEMPTS:
        return
    qid = _resolve_wikidata(entity)
    _persist_outcome(entity_id, qid)
```

`_resolve_wikidata` tries MB-link first, falls back to `episodes.wikidata.find_candidates`, and uses an LLM picker only when there are 2+ candidates. `_persist_outcome` increments `wikidata_attempts`, stamps `wikidata_last_attempted_at`, sets status to RESOLVED on success or NOT_FOUND when attempts reach MAX_ATTEMPTS.

`wikidata_queue = Queue("wikidata_enrichment", concurrency=1, worker_concurrency=1)` — singleton across the cluster.

Wrote `episodes/management/commands/enrich_entities.py` with `--retry-failed` and `--limit` flags. Wrote 13 tests in `episodes/tests/test_enrichment.py` covering MB-first / Wikidata fallback / multi-candidate LLM picker / failure modes / idempotency. All 13 pass.

**Task 7 — Episode pipeline queue + dedup.** Added `episode_queue = Queue("episode_pipeline", concurrency=settings.RAGTIME_EPISODE_CONCURRENCY)` to `episodes/workflows.py`. Added `mark_queued` step. `process_episode`'s recovery dispatch and `run_agent_recovery` switched from `DBOS.start_workflow` to `episode_queue.enqueue` (with `mark_queued` set first).

`workflows.create_run_step` now transitions `QUEUED → from_step` (or first PIPELINE_STEP) so each step's precondition check (`if status != EXPECTED: return`) still works.

`episodes/signals.py` switched to `episode_queue.enqueue` and sets `Episode.Status.QUEUED` via queryset `.update()` (bypasses `post_save`, no recursion). Wrapped the enqueue in `try/except DBOSException` so test environments and management commands without an initialized DBOS just log and continue. Re-added the `from dbos import DBOS` import as a back-compat shim because 92 existing test patches reference `episodes.signals.DBOS`.

`episodes/admin.py` reprocess action: switched to enqueue, sets `Episode.Status.QUEUED` (replacing the old `episode.status = from_step` write — workflow handles that transition now).

`episodes/processing.py` `get_active_run` switched from `.filter(...).order_by(...).first()` to `.get(episode=, status=RUNNING)`. The partial unique constraint guarantees at most one match; `MultipleObjectsReturned` would mean the constraint or migration is broken — surface it loudly.

Updated `episodes/tests/test_signals.py` to patch `episodes.workflows.episode_queue` instead of `episodes.signals.DBOS`. Added a test asserting `episode.status == QUEUED` after creation. All 4 signal tests pass.

Ran the full suite — 10 regressions: 6 `test_wrong_status` failures across `test_chunk` / `test_download` / `test_extract` / `test_resolve` / `test_summarize` / `test_transcribe` (because the QUEUED transition in the signal handler now changes PENDING → QUEUED automatically), plus 4 errors: 1 admin reprocess test (still patching `DBOS.start_workflow`), 3 configure wizard tests (the new MusicBrainz + Pipeline sections need additional mock inputs).

Bulk-fixed the wrong-status tests with `sed -i '' 's/status=Episode.Status.PENDING,/status=Episode.Status.QUEUED,/'` and the matching assertion. Updated the admin reprocess test to mock `episodes.workflows.episode_queue` and assert QUEUED status. Added 6 new mock inputs + 1 new getpass entry to each of the three configure wizard tests (MusicBrainz DB host/port/name/user/schema + Pipeline EPISODE_CONCURRENCY + MB DB password). All 322 tests pass.

**Task 8 — Slim payload + hydration.** Rewrote `episodes/vector_store.py`:

- `ChunkSearchResult` gains `entity_ids`, `entity_names`, `musicbrainz_ids`, `wikidata_ids` fields (all default empty lists for backward compat).
- `ensure_collection` now catches `UnexpectedResponse` with `status_code == 409` and treats it as success.
- `search()` returns `_hydrate_hits(hits)` which keeps Qdrant's score order, builds a `chunk_id → score` map, runs one Postgres query (`Chunk.objects.select_related("episode").filter(pk__in=chunk_ids)`) plus one for entities (`EntityMention.objects.select_related("entity").filter(chunk_id__in=chunk_ids)`), and constructs the full `ChunkSearchResult` per hit. Skips chunks with no Postgres row (logs a warning) — guards against stale Qdrant points mid-reprocess.

`episodes/embedder.py` `_build_payloads` now writes only `chunk_id` / `episode_id` / `language` / `entity_ids`. Removed the audio_url fallback logic from the payload (it lives in the Episode model and gets hydrated at search time).

`episodes/apps.ready()` calls a new `_init_qdrant` method that ensures the collection once at startup, gated by the same `runserver` / `uvicorn` check used for DBOS. Errors at startup are logged but not fatal — the per-embed `ensure_collection` call remains as a fallback.

Updated `episodes/tests/test_embed.py`:

- Old payload assertions (`payload["text"]`, `payload["episode_audio_url"]`, `payload["entity_names"]`) replaced with slim-payload assertions (`set(payload.keys()) == {"chunk_id", "episode_id", "language", "entity_ids"}`).
- New `SearchHydrationTests` class (4 tests) exercises the Postgres hydration path: episode title/audio_url come through, entity_names + musicbrainz_ids + wikidata_ids hydrate from `EntityMention → Entity`, Postgres title edits are visible without re-embedding, stale Qdrant points (no Postgres chunk) are skipped.

All 23 embed tests pass. `chat.tests` (13 tests, the Scott search wrapper) pass without changes — the `ChunkSearchResult` shape is back-compat thanks to the new fields defaulting to empty lists.

**Task 9 — Full test suite.** `uv run python manage.py test` — 322 tests pass.

### User

> Carry out the remaining TODOs and then create a PR.

### Assistant

Wrote three docs per AGENTS.md format: plan copy, feature doc, planning session transcript. Updated CHANGELOG, top-level README, AGENTS.md, doc/README.md. Ran `manage.py check` and `manage.py migrate --plan` against a fresh test DB to confirm migrations apply cleanly.

Skipped the destructive cutover steps (drop `ragtime` DB / Qdrant collection / re-ingest) — those depend on the user having the MB Postgres DB stood up locally and active API keys, and are documented in the feature doc as the on-device verification recipe.

Created the PR with the full doc bundle (plan + feature doc + both session transcripts + CHANGELOG entry).
