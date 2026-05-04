# DBOS Enqueue-Only Clients for Management Commands

**Date:** 2026-05-04

## Problem

`manage.py enrich_entities` and `manage.py submit_episode` were both listed in `episodes/apps.py:_init_dbos`'s `_DBOS_COMMANDS` set. That meant each one called `DBOS.launch()` on startup, becoming a full DBOS worker — even though both commands only need to write a row to `dbos.workflow_status` (i.e., enqueue) and exit. With uvicorn already running as the actual worker, two visible regressions surfaced:

1. **Queue contention.** Both processes' dispatchers polled `dbos.workflow_status` for ENQUEUED rows on the same queue (e.g. `wikidata_enrichment`, concurrency=1). DBOS logged `WARNING: Contention detected in queue thread for wikidata_enrichment. Increasing polling interval to 2.00.`
2. **Shutdown race.** Between the enqueue and the management command's exit, the local dispatcher picked up one of the freshly-enqueued tasks and tried to submit it to the local executor — which had already been torn down by Python's atexit handler. DBOS logged `ERROR: Error executing workflow …: cannot schedule new futures after shutdown`. The task wasn't lost (its DB row was still ENQUEUED, so uvicorn picked it up) but the alarming-looking log polluted every backfill run.

The cosmetic-but-noisy errors will recur for any new one-shot command that enqueues onto a DBOS queue while a long-running worker is consuming it.

## Changes

`episodes/apps.py:_init_dbos` now distinguishes two roles:

- **Workers** (`uvicorn`, `runserver`) call `DBOS.launch()` and listen to every declared queue.
- **Clients** (`submit_episode`, `enrich_entities`) call `DBOS.listen_queues([])` immediately before `DBOS.launch()`. The instance still launches (the system database engine, `_sys_db`, is created inside `launch()` and is required by `Queue.enqueue` → `start_workflow`), but the queue dispatcher iterates over an empty list and never tries to dequeue from `episode_pipeline` or `wikidata_enrichment`. No contention warning, no shutdown race.

The issue's recommended Option 1 was "skip `launch()` for clients". That doesn't actually work: `DBOS._sys_db` raises `DBOSException("System database accessed before DBOS was launched")` if `_launched` is false, and `Queue.enqueue` reaches `dbos._sys_db` via `start_workflow`. `listen_queues([])` is the working refinement of Option 1 — DBOS still launches fully but listens to no application queues.

Verified at `dbos/_queue.py:200-205`: when `dbos._listening_queues is not None`, the queue manager thread iterates over that list (plus the always-present internal queue) instead of `dbos._registry.queue_info_map`. With `listen_queues([])`, the manager only tracks the internal queue, which is unrelated to `episode_pipeline` and `wikidata_enrichment`.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `_WORKER_COMMANDS` | `{"runserver"}` | Plus `is_uvicorn` (matched on `sys.argv[0]`). These start the full dispatcher. |
| `_CLIENT_COMMANDS` | `{"submit_episode", "enrich_entities"}` | Enqueue-only; never dequeue from application queues. |
| `DBOS.listen_queues([])` | `[]` | Empty list = no application queues dispatched in this process. The internal queue is always present and is unrelated to user queues. |

## Verification

**Automated**

```bash
uv run python manage.py check
uv run python manage.py test --noinput  # 371 tests, OK
```

**Manual smoke test (requires Postgres + Qdrant up)**

```bash
# Terminal 1: start the worker
uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8765
# Terminal 2: run a client while the worker is up
uv run python manage.py enrich_entities --limit 1 --retry-failed
```

Expected client log lines:

```
(dbos:_queue.py:207) Listening to 0 queues:
(dbos:_dbos.py:680) DBOS launched!
Enqueued 1 entity for Wikidata enrichment.
```

No `Contention detected` warning. No `cannot schedule new futures after shutdown` error. The `Failed to start admin server: [Errno 48] Address already in use` warning from the client is unrelated (each DBOS process tries to bind admin port 3001) and was present before this change.

The same flow works for `submit_episode <url>` — it writes one row to `dbos.workflow_status` (queue `episode_pipeline`, status `ENQUEUED`) and exits. uvicorn picks it up.

## Files modified

- `episodes/apps.py` — split `_DBOS_COMMANDS` into `_WORKER_COMMANDS` and `_CLIENT_COMMANDS`; client path calls `DBOS.listen_queues([])` before `DBOS.launch()` so no queue dispatcher polls our queues.
- `doc/plans/2026-05-04-dbos-enqueue-only-clients.md` — plan.
- `doc/features/2026-05-04-dbos-enqueue-only-clients.md` — this file.
- `doc/sessions/2026-05-04-dbos-enqueue-only-clients-planning-session.md` — planning transcript.
- `doc/sessions/2026-05-04-dbos-enqueue-only-clients-implementation-session.md` — implementation transcript.
- `CHANGELOG.md` — entry under `## 2026-05-04`.
