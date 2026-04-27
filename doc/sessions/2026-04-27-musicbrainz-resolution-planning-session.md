# MusicBrainz Resolution — Planning Session

**Date:** 2026-04-27

**Session ID:** 2a9d5c4e-1263-4d89-a97a-973e9193a72a

## Summary

Planned the switch from Wikidata-first foreground entity resolution to MusicBrainz-first foreground resolution + background Wikidata enrichment. Scope expanded mid-session with two user-driven additions:

1. **Slim Qdrant payload + Postgres hydration**: instead of duplicating episode metadata into every Qdrant point, store only `chunk_id` + a few server-side filterable fields and resolve everything else from Postgres at search time. This eliminated the need for any Qdrant payload mutation by the background enrichment workflow.
2. **External-reviewer parallelism findings**: race on `Entity.objects.create()` for the same `(entity_type, name)` across parallel resolvers, duplicate workflows for the same episode binding step bookkeeping to the wrong run, and Qdrant `ensure_collection()` racing under parallel embeds.

A third user question — "what happens when more than `RAGTIME_EPISODE_CONCURRENCY` episodes are submitted at once?" — drove the introduction of `Episode.Status.QUEUED` so the row visibly reflects "waiting for a worker" before DBOS picks it up.

The final plan was approved with four decisions: (1) non-MB types use the same background Wikidata enrichment as MB types; (2) `RAGTIME_EPISODE_CONCURRENCY=4`; (3) MB lives in a separate Postgres database in the same instance, accessed via raw psycopg; (4) full DB regen + re-ingest at cutover (RAGtime is pre-production).

## Detailed conversation

### User

> Currently, in the entity extraction and resolution steps, we work with wikidata IDs. The problem with the approach is that we need to throttle the calls to the Wikidata API. We want to switch to using MusicBrainz and resolve to MusicBrainz IDs via a local database. I have built https://github.com/rafacm/musicbrainz-database-setup to be able to add the MusicBrainz database to the local Postgres database. Once we can resolve an entity to a MusicBrainz ID, we can get to that entity's Wikidata ID via the MusicBrainz database external links information. Nevertheless, some entity types are not included in the MusicBrainz database so we still want to keep the Wikidata entity linking logic. We want to speed up the end-to-end pipeline run for a given episode so we want to move to the background the Wikidata entity linking logic. We also want to make sure we can process several episodes in parallel. Since we want to throttle Wikidata API calls, only one instance of that service should be run even if several episodes are being processed in parallel. Maybe one option is to embed the episode chunks with the resolved MusicBrainz entities (since they can be queried locally and in parallel) and in the background update the Qdrant items metadata as the Wikidata entities are being resolved. Note that we can also reuse Wikidata entities in the sense that when we process an episode about Django Reinhardt and we resolve the Wikidata IDs mentioned there, when processing the second, we should not make queries to resolve entities that were already resolved for the first one.

### Assistant

Spawned three Explore agents in parallel to ground the plan in the actual code:

1. **Entity extraction & resolution** — to understand how `episodes/resolver.py` currently calls Wikidata, where `Entity` / `EntityMention` / `EntityType` live, and how the resolver LLM prompt fuzzy-matches against existing entities. Found the Wikidata token bucket at `episodes/wikidata.py:18-44` (5 req/s in-process global), the resolver's two paths (no-existing-entities vs. with-existing), and the Qdrant payload structure in `embedder.py`.

2. **DBOS workflow & parallelism** — to understand how multiple episodes can run concurrently. Found that DBOS workflows are PostgreSQL-checkpointed, `process_episode` is fired via `post_save` signal in `episodes/signals.py:17-23` and admin reprocess in `episodes/admin.py:290-312`, and there are currently no concurrency controls beyond DBOS's internal queue.

3. **MusicBrainz repo + embeddings + entity-type coverage** — fetched the [musicbrainz-database-setup](https://github.com/rafacm/musicbrainz-database-setup) README to understand schema (artist/release_group/work/place/label/area + `*_alias` tables + external `l_<entity>_url` → `url` joins), inspected the embed step to understand Qdrant payload shape, and mapped each of RAGtime's 14 entity types to MB equivalents (8 covered, 6 not — recording_session/year/historical_period/music_genre/musical_instrument/role).

Drafted a plan with: new `episodes/musicbrainz.py` (raw psycopg, lazy `ConnectionPool`), MB-first foreground resolver, background `enrich_entity_wikidata` workflow on a DBOS Queue with `concurrency=1` (singleton), new fields on `Entity` (`musicbrainz_id`, `wikidata_status`, `wikidata_attempts`, `wikidata_last_attempted_at`) and `EntityType` (`musicbrainz_table`, `musicbrainz_filter`), `episode_pipeline` queue with `RAGTIME_EPISODE_CONCURRENCY` cap.

The first plan version still proposed updating Qdrant payloads from the enrichment workflow.

### User

> An additional question, we are currently embedding quite a bit of information as metadata in the Qdrant embeddings. Instead of doing that, why can't we enrich the query results to Qdrant with queries to the database to add that information?

### User

> Regarding the episode ingestion parallelisation, I got this feedback from an external technical reviewer:
>
> High: cross-episode entity resolution is not fully parallel-safe. In episodes/resolver.py:212, the transaction includes Wikidata/LLM work and then sometimes calls Entity.objects.create(...) directly for new names in episodes/resolver.py:279 and episodes/resolver.py:293. If two episodes resolve the same new (entity_type, name) at the same time, both can decide the entity does not exist; one insert wins, the other can hit the unique_entity_type_name constraint and fail the whole resolving step. Some branches use get_or_create, but not all.
>
> High: duplicate workflows for the same episode are unsafe. process_episode creates a new run every time without checking for an existing active run in episodes/workflows.py:29, and run bookkeeping finds "the most recent RUNNING run" by episode in episodes/processing.py:36. If the same episode is queued twice, step completion/failure can attach to the wrong run. Admin reprocessing can also start a workflow directly in episodes/admin.py:308. This is mostly a same-episode concurrency issue, but it matters before enabling broader parallelism.
>
> Medium: first-time parallel embedding can race Qdrant collection creation. embed_episode calls store.ensure_collection() for every episode in episodes/embedder.py:80. ensure_collection() checks collection_exists then creates in episodes/vector_store.py:82. If two embedding steps reach an empty Qdrant…

### Assistant

Both messages folded into the plan as substantive design changes:

**On the slim Qdrant payload**: agreed and replaced the "Qdrant updates" section with a "slim payload + Postgres-side hydration" approach. The new payload stores only `chunk_id` + `episode_id` + `language` + `entity_ids`. `vector_store.search()` issues one Postgres query keyed on the returned chunk_ids to hydrate the full `ChunkSearchResult`. **This eliminates the need for any Qdrant write from the enrichment workflow** — updating `Entity.wikidata_id` in Postgres is enough because the next search reads through the FK. Single source of truth, no `set_payload` gymnastics.

**On the reviewer's findings**: added a "Parallel-safety fixes" section to the plan:

- *Entity create race*: replace every `Entity.objects.create` in the resolver with `get_or_create`, wrap candidate creation in a Postgres transaction-scoped `pg_advisory_xact_lock(hashtextextended('<type_id>:<name>', 0))`, sorted to enforce a global lock-acquisition order (no deadlocks between resolvers that share names), plus an `IntegrityError` retry as defense-in-depth.
- *Duplicate workflows per episode*: partial unique constraint `unique_running_run_per_episode` (`episode` + `WHERE status='running'`); switch `processing.get_active_run` from `.first()` to `.get()` so duplicates raise loudly rather than silently picking one.
- *Qdrant collection race*: move `ensure_collection()` to `episodes/apps.ready()` (one-time at startup) and make `create_collection()` 409-tolerant for parallel cold starts.

Asked four clarifying questions via AskUserQuestion: how to handle non-MB entity types (background enrichment vs. skip Wikidata vs. foreground for these only), default for `RAGTIME_EPISODE_CONCURRENCY`, MB DB layout, and whether to re-embed READY episodes after the slim-payload migration.

User selected the recommended option for all four.

### User

> Since this is not yet a released project, it's OK to regenerate the database and re-ingest the podcast episodes

### Assistant

Updated the existing pre-prod feedback memory (`feedback_reembed_ok_preprod.md`) to extend it: re-embedding AND full Postgres regeneration + re-ingestion are both acceptable, and DB-join hydration is fine when chosen for architectural reasons rather than as a workaround to avoid re-embedding. Updated the plan's rollout section to favor clean-slate over backfill — no data migrations, no compat shims. Updated the "Decisions" block to reflect the four confirmed choices.

### User

> What happens if more than four projects are posted to be ingested? In which state will the episodes be that have to wait for ingestion?

### Assistant

Walked through the DBOS queueing semantics: `episode_queue.enqueue()` writes a row to DBOS's PostgreSQL workflow table; workers pick them up FIFO as slots free; no fixed ceiling at podcast scale. Without a status change, the `Episode.status` field would just stay at `PENDING`, indistinguishable from "freshly submitted, signal hasn't fired yet" or "stuck because something's broken". Bad UX.

Added a new `Episode.Status.QUEUED` (between `PENDING` and `SCRAPING` in choices but **not** part of `PIPELINE_STEPS` — it's a pre-pipeline state). The `post_save` signal handler and admin reprocess action set this immediately *before* calling `episode_queue.enqueue(...)`. The first DBOS step inside `process_episode` (`create_run_step`) transitions `QUEUED → from_step` (or first PIPELINE_STEP). Admin list filter automatically picks it up via `list_filter = ("status", ...)`.

Wrote a state-summary table:

| Status | Meaning |
|---|---|
| `PENDING` | Row created, not yet enqueued. Transient (milliseconds). |
| `QUEUED` | Enqueued in DBOS, waiting for a worker slot. |
| `SCRAPING / … / EMBEDDING` | Actively being processed. |
| `READY` | Pipeline complete. Wikidata enrichment may still be pending in the background. |
| `FAILED` | A step failed and recovery couldn't resolve it. |

Re-called `ExitPlanMode`. Plan was approved, saved to `/Users/rafa/.claude/plans/currently-in-the-entity-iridescent-pond.md`.
