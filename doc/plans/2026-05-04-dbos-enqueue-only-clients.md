# DBOS Enqueue-Only Clients for Management Commands

**Date:** 2026-05-04

## Problem

Issue #113 — `manage.py enrich_entities` (and, by extension, `manage.py submit_episode`) is registered as a DBOS worker by `episodes/apps.py:_init_dbos`'s `_DBOS_COMMANDS = {"runserver", "submit_episode", "enrich_entities"}`. That makes the command call `DBOS.launch()` on startup, spinning up a full queue dispatcher inside its own process. The command then enqueues N entries and exits.

When uvicorn is also running (which it must be, to actually drain the queue), two cosmetic-but-noisy regressions surface:

1. Both processes' dispatchers race over `dbos.workflow_status` for ENQUEUED rows on the same queue. `WARNING: Contention detected in queue thread for wikidata_enrichment.`
2. Between enqueue and exit, the client's local dispatcher dequeues one entry and tries to submit it to the local executor — which has already been torn down by `atexit`. `ERROR: cannot schedule new futures after shutdown`.

The work isn't lost (the row stays ENQUEUED until uvicorn picks it up), but the noise is alarming and will be reproduced by any new one-shot enqueue command.

## Goal

Management commands that only need to enqueue (`submit_episode`, `enrich_entities`) should not start a queue dispatcher in their own process. uvicorn (the long-running worker) is the only process that should dispatch from `episode_pipeline` and `wikidata_enrichment`.

## Approach

The issue lays out three options. Recommended: Option 1 — "don't `launch()` from the client, only instantiate DBOS". The risk flagged in the issue: confirm `Queue.enqueue` works without `launch()`.

**Investigation finding.** `Queue.enqueue` calls `start_workflow(execute_workflow=False)`, which writes to `dbos.workflow_status` via `dbos._sys_db`. But `DBOS._sys_db` is a property that raises `DBOSException("System database accessed before DBOS was launched")` if `_launched` is false (verified at `.venv/.../dbos/_dbos.py:494-497`). So bare "skip launch" does NOT work; we hit the exception on the first enqueue.

**Refinement that works.** DBOS exposes `DBOS.listen_queues(queues: List[Queue])` — call before `launch()` to limit which queues this process's dispatcher polls. Pass `[]` to listen to no application queues. The dispatcher still starts (alongside `_sys_db` and the executor), but its inner loop iterates over an empty list of queues plus only the internal queue (which is unrelated to ours). No contention with uvicorn, and no entry from our queues ever reaches the local executor — so no shutdown race.

This is the same "client posture" Option 1 asks for, achieved through DBOS's official knob. Tests stay unchanged.

## Implementation

`episodes/apps.py:_init_dbos`:

1. Split `_DBOS_COMMANDS` into `_WORKER_COMMANDS = {"runserver"}` and `_CLIENT_COMMANDS = {"submit_episode", "enrich_entities"}`.
2. Compute `is_worker` from uvicorn detection + `_WORKER_COMMANDS`, and `is_client` from `_CLIENT_COMMANDS`.
3. Skip DBOS init unless either is true.
4. After constructing `DBOS(config=…)` but before `DBOS.launch()`: if `is_client and not is_worker`, call `DBOS.listen_queues([])`.

No changes to the management commands themselves — `enqueue_entities()` and the post-save signal that enqueues `process_episode` keep working unchanged because the DBOS instance is still launched (just listening to nothing).

## Verification

- `uv run python manage.py test --noinput` — full suite.
- `uv run python manage.py check` — system check.
- Manual: start uvicorn; run `manage.py enrich_entities --limit 1 --retry-failed` in a second shell. Confirm the client logs `Listening to 0 queues:` and exits without `Contention detected` or `cannot schedule new futures after shutdown`. Confirm the workflow row appears in `dbos.workflow_status` with status `ENQUEUED` and the queue thread name from uvicorn's process.

## Out of scope

- Replacing DBOS with another workflow system.
- Eliminating the `Failed to start admin server: [Errno 48] Address already in use` warning when both processes try to bind admin port 3001 (separate cosmetic issue, predates this change).
- A separate worker daemon (uvicorn already serves this role).

## Acceptance criteria (from issue #113)

- [x] `manage.py enrich_entities` enqueues without starting an active queue dispatcher inside its own process.
- [x] When uvicorn is running, `manage.py enrich_entities` produces no "Contention detected" warning and no "cannot schedule new futures after shutdown" error.
- [x] uvicorn (the actual worker) still drains the freshly-enqueued workflows correctly.
- [x] Same fix applied to `submit_episode`.
- [x] `core/tests/test_configure.py` and existing signal/admin tests continue to pass.
