# MusicBrainz-first entity resolution + background Wikidata enrichment

**Date:** 2026-04-27

## Problem

The foreground `resolve` step (pipeline step 8) called Wikidata's public API for every distinct entity name. A global in-process token bucket (`episodes/wikidata.py`, 5 req/s) throttled all parallel pipelines: even with multiple episodes running concurrently they queued behind one bucket. Episodes with ~50 unique entities spent tens of seconds to minutes in resolution before they could embed and reach `READY`.

A separate concern flagged by an external reviewer: cross-episode `Entity.objects.create(...)` races (parallel resolvers picking different canonical names for the same name), duplicate `process_episode` workflows attaching step bookkeeping to the wrong `ProcessingRun`, and `ensure_collection()` racing under parallel embeds.

## Changes

### 1. MusicBrainz-first foreground resolution

Local MusicBrainz Postgres database (loaded via [musicbrainz-database-setup](https://github.com/rafacm/musicbrainz-database-setup)) replaces the Wikidata API in the foreground path. New module `episodes/musicbrainz.py` exposes:

- `find_candidates(name, entity_type, *, limit=10)` — case-insensitive lookup against the main entity table + alias table, ranked exact-match first.
- `get_wikidata_qid(mbid, entity_type)` — joins `l_<entity>_url` → `url`, parses Q-ID from the Wikidata URL.

Raw psycopg via `psycopg_pool.ConnectionPool` (lazy, min=1 / max=8, autocommit, `search_path = $RAGTIME_MUSICBRAINZ_SCHEMA,public`). Bypasses the Django ORM — the MB schema is huge and read-only, building Django models would be invasive without giving us anything we need.

`episodes/initial_entity_types.yaml` adds `musicbrainz_table` + `musicbrainz_filter` to each type. Eight types map to MB tables (artist/release_group/work/place/label/area); six types (year, role, instrument, genre, recording_session, historical_period) have no MB equivalent and skip the candidate lookup.

`episodes/resolver.py` is rewritten:

- `_fetch_musicbrainz_candidates()` replaces `_fetch_wikidata_candidates()`.
- Foreground never calls Wikidata.
- LLM resolution prompt and response schema use `musicbrainz_id` (UUID) instead of `wikidata_id`.
- Race-safe writes: `get_or_create` everywhere + per-name `pg_advisory_xact_lock(hashtextextended('<type_id>:<name>', 0))` (sorted to enforce a global lock-acquisition order — no deadlocks between resolvers that share names) + `IntegrityError` retry.
- After commit, enqueues `enrich_entity_wikidata` for newly-created entities.

### 2. Background Wikidata enrichment

New module `episodes/enrichment.py`:

```python
wikidata_queue = Queue("wikidata_enrichment", concurrency=1, worker_concurrency=1)

@DBOS.workflow()
def enrich_entity_wikidata(entity_id): ...
```

`concurrency=1` + `worker_concurrency=1` guarantees the enrichment workflow is a singleton across the cluster, so Wikidata's 5 req/s rate limit is satisfied by serialization. Strategy per entity:

1. Short-circuit if already resolved or attempts exhausted.
2. If `Entity.musicbrainz_id` is set, try the local MB → Wikidata link first (no network).
3. Fall back to Wikidata search + LLM picker.
4. Persist `Entity.wikidata_id`, `wikidata_status`, `wikidata_attempts`, `wikidata_last_attempted_at`.
5. **No Qdrant write** — search-time hydration picks up new wikidata_ids automatically.

Business logic lives in plain `*_impl` / helper functions; DBOS decorators wrap one-line calls so tests can exercise the logic without launching DBOS.

`manage.py enrich_entities [--retry-failed] [--limit N]` backfills any entity in PENDING (or, with `--retry-failed`, FAILED/NOT_FOUND) status.

### 3. Slim Qdrant payload + Postgres-side hydration

Old payload duplicated Postgres-derivable data into every Qdrant point (episode title, urls, text, entity names, …). New payload is the minimum needed for server-side filtering:

```python
{"chunk_id": int, "episode_id": int, "language": str, "entity_ids": [int]}
```

`vector_store.search()` queries Qdrant for chunk IDs + scores, then issues one Postgres query keyed on those IDs to hydrate the full `ChunkSearchResult` (episode title, audio_url, image_url, chunk text, entity names, MBIDs, Wikidata IDs). Top-k is 5–10, so the hydration query is trivial.

Consequences:

- Editing `Episode.title` is visible immediately — no re-embedding, no Qdrant payload mutation.
- Background Wikidata enrichment updates `Entity.wikidata_id` in Postgres only — the next search reads through the FK.
- Smaller Qdrant index, less memory.

### 4. Episode-level parallelism with explicit queue

```python
episode_queue = Queue("episode_pipeline", concurrency=settings.RAGTIME_EPISODE_CONCURRENCY)
```

`RAGTIME_EPISODE_CONCURRENCY=4` default. `episodes/signals.py` and `episodes/admin.py` switch from `DBOS.start_workflow` to `episode_queue.enqueue`. Both set `Episode.Status.QUEUED` immediately so the row visibly reflects "waiting for a worker" before DBOS picks it up. Recovery dispatch in `workflows.process_episode` and `workflows.run_agent_recovery` likewise enqueues through the queue.

`workflows.create_run_step` transitions `QUEUED → from_step` (or first PIPELINE_STEP) when the workflow starts — keeps the per-step precondition checks (`if status != EXPECTED: return`) intact.

### 5. Parallel-safety guards

| Concern | Guard |
|---|---|
| Two resolvers create same `(entity_type, name)` simultaneously | `get_or_create` + advisory lock + `IntegrityError` retry |
| Two `process_episode` workflows for same episode | Partial unique constraint `unique_running_run_per_episode` (`WHERE status='running'`) + `processing.get_active_run` uses `.get()` (loud on duplicates) |
| Qdrant collection check-then-create race | `episodes/apps.ready()` ensures the collection once at process startup; `ensure_collection()` is 409-tolerant for parallel cold starts |

### 6. New `Episode.Status.QUEUED`

Inserted between `PENDING` and `SCRAPING` in the choices list (but not part of `PIPELINE_STEPS`). The `post_save` signal and admin reprocess action set this immediately at enqueue time. Workflow's `create_run_step` transitions out of QUEUED into the first pipeline step. Admin list filter automatically picks it up via `list_filter = ("status", ...)`.

## Key parameters

| Constant / env var | Default | Why |
|---|---|---|
| `RAGTIME_EPISODE_CONCURRENCY` | `4` | Balanced default — provider rate limits (OpenAI, Whisper) handle 4 parallel episodes comfortably. Backlogs beyond 4 sit in QUEUED state. |
| `enrichment.MAX_ATTEMPTS` | `3` | After 3 attempts, status moves PENDING → NOT_FOUND. Prevents infinite retry loops on entities Wikidata genuinely doesn't have. |
| `wikidata_queue` `concurrency` / `worker_concurrency` | `1 / 1` | Singleton enrichment worker across the cluster — Wikidata's 5 req/s rate limit is satisfied by serialization, no shared throttle needed. |
| `psycopg_pool.ConnectionPool` for MB | `min_size=1, max_size=8` | Covers `RAGTIME_EPISODE_CONCURRENCY` parallel episodes plus headroom. |
| `RAGTIME_MUSICBRAINZ_DB_*` | inherits `RAGTIME_DB_*` | Default to the same Postgres instance with `dbname=musicbrainz` — matches the standard musicbrainz-database-setup output. Override only if MB lives elsewhere. |
| `RAGTIME_MUSICBRAINZ_SCHEMA` | `musicbrainz` | The schema MB tables live in inside the MB database. |

## Verification

End-to-end on-device:

1. **Stand up the MB Postgres DB** by following [musicbrainz-database-setup](https://github.com/rafacm/musicbrainz-database-setup). The setup creates a `musicbrainz` database in your existing Postgres instance.
2. **Configure RAGtime** to point at it: `uv run python manage.py configure` and accept the MusicBrainz DB defaults.
3. **Reset Postgres + Qdrant**: `uv run python manage.py dbreset` (drops `ragtime` DB and the Qdrant collection).
4. **Apply migrations** (loads new entity-type fields from YAML automatically): `uv run python manage.py migrate && uv run python manage.py load_entity_types`.
5. **Run uvicorn**: `uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000`.
6. **Submit a test episode** via the Django admin or `Episode.objects.create(url=...)`. Status should move PENDING → QUEUED → SCRAPING → … → READY in seconds (modulo provider latency for download/transcription).
7. **Verify MB IDs**: `Entity.objects.filter(musicbrainz_id__gt='').count()` should be > 0 for jazz-related entities.
8. **Verify enrichment runs**: `Entity.objects.filter(wikidata_id='').filter(wikidata_status='pending')` shrinks over time as the singleton worker drains the queue.
9. **Submit two episodes in parallel** via admin Reprocess; both should run concurrently (observe overlapping `ProcessingRun.started_at` timestamps).
10. **Scott**: ask a question that hits a freshly-enriched chunk; verify citations work and `wikidata_ids` appears in the response payload without any Qdrant write having occurred.

Tests: `uv run python manage.py test` — 322 tests pass (61 new tests on top of the 261 baseline).

## Files modified

**New**:
- `episodes/musicbrainz.py` — psycopg-pool reader for MB DB.
- `episodes/enrichment.py` — DBOS singleton-queue Wikidata workflow.
- `episodes/management/commands/enrich_entities.py` — backfill command.
- `episodes/tests/test_musicbrainz.py` — 12 tests for MB lookups.
- `episodes/tests/test_enrichment.py` — 13 tests for the enrichment workflow.
- `episodes/migrations/0020_*.py` — schema additions.

**Modified**:
- `episodes/models.py` — `Episode.Status.QUEUED`, MB & enrichment fields on `Entity` + `EntityType`, partial unique constraint on `ProcessingRun`.
- `episodes/initial_entity_types.yaml` — MB table mapping per type.
- `episodes/resolver.py` — full rewrite for MB-first, race-safe creates, per-name advisory lock, foreground never calls Wikidata.
- `episodes/embedder.py` — slim payload (chunk_id / episode_id / language / entity_ids only).
- `episodes/vector_store.py` — slim payload schema, search-time Postgres hydration, 409-tolerant `ensure_collection`.
- `episodes/apps.py` — bootstraps Qdrant collection once at process startup.
- `episodes/workflows.py` — `episode_pipeline` queue, deterministic QUEUED → step transition, recovery dispatch goes through queue.
- `episodes/processing.py` — `get_active_run` uses `.get()`.
- `episodes/signals.py` — switches to queue.enqueue + `DBOSException` swallow for non-runtime contexts.
- `episodes/admin.py` — reprocess action enqueues + sets QUEUED status.
- `episodes/management/commands/load_entity_types.py` — populates new YAML fields.
- `ragtime/settings.py` + `.env.sample` — `RAGTIME_MUSICBRAINZ_DB_*`, `RAGTIME_MUSICBRAINZ_SCHEMA`, `RAGTIME_EPISODE_CONCURRENCY`.
- `core/management/commands/_configure_helpers.py` — wizard sections for MusicBrainz + Pipeline.
- `pyproject.toml` — adds `psycopg_pool>=3.2,<4`.
- Tests: `test_resolve.py`, `test_signals.py`, `test_admin.py`, `test_embed.py`, `test_chunk.py`, `test_download.py`, `test_extract.py`, `test_summarize.py`, `test_transcribe.py`, `core/tests/test_configure.py` (PENDING → QUEUED expectations + new wizard inputs).
