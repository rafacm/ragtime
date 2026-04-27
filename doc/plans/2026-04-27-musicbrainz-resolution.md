# Plan: MusicBrainz-first entity resolution with background Wikidata enrichment

**Date:** 2026-04-27

## Context

Today the `resolve` step (pipeline step 8) is the slowest part of episode ingestion. For every distinct entity name (artist, album, label, …), `episodes/resolver.py` calls the Wikidata public API (`wbsearchentities` + `wbgetentities`) to fetch candidates, then asks an LLM to pick the best Q-ID. The Wikidata client (`episodes/wikidata.py`) uses an in-process token bucket capped at **5 req/s**, which is the global throttle for *all* parallel episode pipelines that share the Uvicorn process. Net effect:

- A single episode with ~50 unique entities can spend tens of seconds to minutes waiting on Wikidata.
- Running multiple episodes "in parallel" via DBOS doesn't help — they all queue behind the same 5 req/s bucket.
- The pipeline can't return a "ready" episode until Wikidata has answered every query.

The user has stood up a separate repo, [musicbrainz-database-setup](https://github.com/rafacm/musicbrainz-database-setup), that imports the full MusicBrainz dump into local Postgres. Local MB lookups are sub-millisecond. MusicBrainz also stores Wikidata external links per entity (via `l_*_url` → `url` joins), so once we have an MBID we can derive its Wikidata Q-ID locally.

**Goal**: foreground pipeline resolves to MBIDs (fast, local, parallel-safe). Wikidata enrichment moves to a single throttled background worker that backfills Wikidata IDs on `Entity` rows. Entities are deduplicated globally, so common names ("Django Reinhardt") only get enriched once across all episodes.

## High-level design

### Pipeline shape (logical)

```
foreground (per episode, parallel-safe):
  scrape → download → transcribe → summarize → chunk → extract
    → resolve (MB-first, no network) → embed → ready

background (singleton, throttled, deduplicated by Entity):
  wikidata_enrichment_queue
    → enrich_entity_wikidata(entity_id)
      → (a) MBID → Wikidata via local MB external links
      → (b) fallback: Wikidata search + LLM picker (rate-limited)
      → update Entity.wikidata_id
```

The episode reaches `READY` as soon as embedding finishes — Wikidata enrichment is decoupled and may complete minutes/hours later without blocking Scott's ability to answer questions.

### Foreground resolution rules

| Type | MusicBrainz table | Foreground behavior |
|---|---|---|
| `musician` | `artist` (type=Person) | MB lookup → MBID |
| `musical_group` | `artist` (type=Group/Orchestra/Choir) | MB lookup → MBID |
| `album` | `release_group` (primary_type=Album) | MB lookup → MBID |
| `composed_musical_work` | `work` | MB lookup → MBID |
| `music_venue` | `place` | MB lookup → MBID |
| `record_label` | `label` | MB lookup → MBID |
| `city` | `area` (type=City) | MB lookup → MBID |
| `country` | `area` (type=Country) | MB lookup → MBID |
| `recording_session`, `year`, `historical_period`, `music_genre`, `musical_instrument`, `role` | — | name-only Entity, defer Wikidata to background |

### Data model changes

`episodes/models.py` — `Entity`:
- `musicbrainz_id: CharField(36, blank, db_index=True)`
- `wikidata_status: CharField(choices=[pending, resolved, not_found, failed], default=pending, db_index=True)`
- `wikidata_attempts: PositiveSmallIntegerField(default=0)`
- `wikidata_last_attempted_at: DateTimeField(null=True, blank=True)`

`episodes/models.py` — `EntityType`:
- `musicbrainz_table: CharField(64, blank)` — empty for non-MB types.
- `musicbrainz_filter: JSONField(default=dict, blank=True)` — e.g. `{"artist_type": "Person"}`.

`episodes/models.py` — `Episode.Status.QUEUED` (between PENDING and SCRAPING) — pre-pipeline state for episodes waiting in the DBOS queue.

`episodes/models.py` — `ProcessingRun`: partial unique constraint `unique_running_run_per_episode` (`episode` + `WHERE status='running'`) — DB-level guard against duplicate workflows for the same episode.

### MusicBrainz integration

New module `episodes/musicbrainz.py`. **Raw psycopg** (not Django ORM) — MB schema has hundreds of tables, building Django models is invasive without giving us anything we need. A lazy `psycopg_pool.ConnectionPool` (min=1, max=8, autocommit) keeps connections isolated from Django's main DB.

Public API:
- `find_candidates(name, entity_type, *, limit=10) -> list[Candidate]` — case-insensitive search of main + alias tables. Candidates have `mbid`, `name`, `sort_name`, `disambiguation`, `type`.
- `get_wikidata_qid(mbid, entity_type) -> str | None` — joins `l_<entity>_url` → `url`, parses Q-ID from `wikidata.org/wiki/Q…` URLs.

Connection params come from `RAGTIME_MUSICBRAINZ_DB_*` env vars (defaults inherit from `RAGTIME_DB_*`).

### Resolver refactor

`episodes/resolver.py`:
- Replaces `_fetch_wikidata_candidates()` with `_fetch_musicbrainz_candidates()`.
- Drops the in-process Wikidata token-bucket call from the foreground path.
- All `Entity.objects.create(...)` replaced with `get_or_create(...)`.
- Per-name advisory lock via `pg_advisory_xact_lock(hashtextextended('<type_id>:<name>', 0))` — sorted to enforce a global lock-acquisition order, eliminating deadlock risk between resolvers that share names. Locks release at txn end.
- `IntegrityError` fallback in `_get_or_create_entity` for the rare case a lock isn't held (test envs without advisory locks, hash collisions).
- LLM response schema returns `musicbrainz_id` (UUID) instead of `wikidata_id`.
- After commit, enqueues background Wikidata enrichment for newly-created entities.

### Background Wikidata enrichment

New module `episodes/enrichment.py`.

```python
wikidata_queue = Queue(
    "wikidata_enrichment",
    concurrency=1,           # one workflow at a time, cluster-wide
    worker_concurrency=1,
)

@DBOS.workflow()
def enrich_entity_wikidata(entity_id): ...
```

Implementation lives in `enrich_entity_wikidata_impl` (plain function, testable without DBOS runtime); the workflow decorator wraps a one-line call. Strategy:

1. Short-circuit if already resolved or attempts exhausted.
2. If `Entity.musicbrainz_id` is set, try the local MB → Wikidata link.
3. Fall back to Wikidata search + LLM picker (rate-limited).
4. Persist `Entity.wikidata_id` / `wikidata_status` / `wikidata_attempts` / `wikidata_last_attempted_at`.
5. **No Qdrant write** — search-time hydration picks up the new wikidata_id automatically (see below).

`MAX_ATTEMPTS = 3`. New `manage.py enrich_entities` command for backfill.

### Episode-level parallelism

New `episode_pipeline` DBOS queue:
```python
episode_queue = Queue("episode_pipeline", concurrency=settings.RAGTIME_EPISODE_CONCURRENCY)
```

`RAGTIME_EPISODE_CONCURRENCY=4` by default. `episodes/signals.py` and `episodes/admin.py` switch from `DBOS.start_workflow` to `episode_queue.enqueue`. Both set `Episode.Status.QUEUED` immediately so the row visibly reflects "waiting for a worker" before DBOS picks it up.

Recovery dispatch (`workflows.process_episode` and `workflows.run_agent_recovery`) likewise enqueues through the same queue.

### Parallel-safety fixes (reviewer feedback)

| Issue | Fix |
|---|---|
| Cross-episode `Entity` create race | `get_or_create` everywhere + per-name `pg_advisory_xact_lock` + `IntegrityError` retry |
| Duplicate workflows per episode | Partial unique constraint `WHERE status='running'`; `processing.get_active_run` switches to `.get()` (loud on duplicates) |
| Qdrant collection creation race | Move `ensure_collection()` to `episodes/apps.ready()` (one-time at startup) + 409-tolerant `create_collection` |

### Slim Qdrant payload + Postgres-side hydration

Today's payload duplicates Postgres-derivable data into every Qdrant point (episode title, urls, text, entity names, …). The new payload is **only** what Qdrant needs for filtering / FK lookup:

```python
{
    "chunk_id": int,         # FK back to Postgres
    "episode_id": int,       # Scott's per-episode filter
    "language": str,         # future per-language filter
    "entity_ids": [int],     # entity-faceted retrieval
}
```

`vector_store.search()` queries Qdrant for chunk IDs + score, then issues one Postgres query keyed on those IDs to hydrate the full `ChunkSearchResult` (episode title, audio_url, image_url, chunk text, entity names, MBIDs, Wikidata IDs). Top-k is small (5–10), so the hydration query is trivial.

**Why this is the right call**:
1. Single source of truth — title/url edits, canonical-name fixes go live without re-embedding.
2. **No Qdrant writes for Wikidata enrichment** — background updates `Entity.wikidata_id` in Postgres, search-time join picks it up.
3. Smaller index, lower memory.

### Files to modify / create

**New**: `episodes/musicbrainz.py`, `episodes/enrichment.py`, `episodes/management/commands/enrich_entities.py`, `episodes/tests/test_musicbrainz.py`, `episodes/tests/test_enrichment.py`, migration `0020_*`.

**Modified**: `episodes/models.py`, `episodes/initial_entity_types.yaml`, `episodes/resolver.py`, `episodes/embedder.py`, `episodes/vector_store.py`, `episodes/apps.py`, `episodes/workflows.py`, `episodes/processing.py`, `episodes/signals.py`, `episodes/admin.py`, `episodes/management/commands/load_entity_types.py`, `episodes/tests/test_*` (8 files), `ragtime/settings.py`, `core/management/commands/_configure_helpers.py`, `core/tests/test_configure.py`, `.env.sample`, `pyproject.toml` (adds `psycopg_pool`).

### Verification

1. **Unit tests** — MB candidate construction (mocked psycopg), resolver MB path, enrichment workflow MB-first / Wikidata-fallback, search-time hydration, slim payload shape.
2. **Race regression** — assert resolver returns `_enqueue_enrichment` ids correctly, advisory lock SQL is issued.
3. **Parallel run** — admin reprocess two episodes simultaneously; observe both reach READY without `unique_entity_type_name` violations.
4. **Latency check** — time the resolve step before/after on a real episode; expect a drop from tens of seconds to <1s.
5. **Scott end-to-end** — query a chunk freshly enriched; Wikidata ID appears in the search result without any Qdrant write.

## Decisions (confirmed with user)

1. **Non-MB entity types** — go through the same background Wikidata enrichment as MB types; foreground creates them with canonical name only.
2. **`RAGTIME_EPISODE_CONCURRENCY`** — default to **4**.
3. **MB DB layout** — separate Postgres database in the same instance (`musicbrainz` DB alongside `ragtime`), accessed via raw psycopg pool.
4. **Rollout** — drop the `ragtime` Postgres DB and the Qdrant collection, run fresh migrations, re-ingest the podcast episodes from scratch. No data migrations, no compat shims (RAGtime is pre-production).
