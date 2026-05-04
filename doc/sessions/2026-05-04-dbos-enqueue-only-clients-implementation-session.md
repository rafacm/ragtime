# DBOS Enqueue-Only Clients — Implementation Session

**Date:** 2026-05-04

**Session ID:** 5b5b2169-5e23-4e06-852f-56035beab570

## Summary

Implemented the plan in `doc/plans/2026-05-04-dbos-enqueue-only-clients.md` on branch `rafacm/dbos-enqueue-only`. Single-file source change: `episodes/apps.py:_init_dbos` now distinguishes worker entrypoints (`uvicorn`, `runserver`) from client management commands (`submit_episode`, `enrich_entities`). Clients call `DBOS.listen_queues([])` immediately before `DBOS.launch()` so the dispatcher iterates over zero application queues — eliminating both the "Contention detected" warning and the "cannot schedule new futures after shutdown" race at exit.

Full test suite (371 tests) passes. Manual smoke test confirmed the behaviour: client logs `Listening to 0 queues:` and exits cleanly while uvicorn runs alongside.

## Detailed conversation

### User

> You are working on issue #113 in the rafacm/ragtime repo: "manage.py enrich_entities should be a DBOS client, not a worker".
>
> [Full implementation brief — branching steps, staleness check, Option 1 implementation guidance, verification, documentation, and PR steps as defined by the parent agent.]

### Assistant

**Staleness check.** Read `episodes/apps.py`, `episodes/management/commands/enrich_entities.py`, and `episodes/management/commands/submit_episode.py`. Confirmed the bug exists: `_DBOS_COMMANDS = {"runserver", "submit_episode", "enrich_entities"}` and `DBOS.launch()` is called unconditionally. Compared worktree HEAD against `origin/main` — same content. Issue not yet implemented.

**Branching.** Created `rafacm/dbos-enqueue-only` from `origin/main` after `git fetch`.

**DBOS source investigation.** Confirmed the issue's risk note — `Queue.enqueue` does not work without `launch()`. Walked through:

- `dbos/_queue.py:74` — `Queue.enqueue` → `start_workflow(execute_workflow=False)`.
- `dbos/_core.py:783` — `start_workflow` calls `_init_workflow` which uses `dbos._sys_db`.
- `dbos/_dbos.py:494` — `_sys_db` property raises `DBOSException` when `_launched` is false.
- `dbos/_dbos.py:548` — `_sys_db_field` is initialised inside `_launch()`, so `launch()` is mandatory.

Pure Option 1 ("skip launch") therefore fails. Discovered `DBOS.listen_queues(queues)` at `dbos/_dbos.py:2925` — sets `_listening_queues`, consulted by the queue manager thread at `dbos/_queue.py:200-205`. With `listen_queues([])`, the manager only tracks the internal queue (unrelated to `episode_pipeline` and `wikidata_enrichment`). This achieves the architectural posture Option 1 wanted via an official DBOS knob.

**Edit.** Reworked `episodes/apps.py:_init_dbos`:

- Replaced `_DBOS_COMMANDS` with `_WORKER_COMMANDS = {"runserver"}` and `_CLIENT_COMMANDS = {"submit_episode", "enrich_entities"}`.
- Added `is_worker` (uvicorn-detection plus worker-set membership) and `is_client` flags. Skip when neither matches.
- After constructing `DBOS(config=…)`, when `is_client and not is_worker`, call `DBOS.listen_queues([])` before `DBOS.launch()`.
- Comment block explains worker vs client roles and why pure "skip launch" doesn't work.

No changes to `enrich_entities.py`, `submit_episode.py`, signals, workflows, enrichment, or any test.

**Tests.**

```bash
uv run python manage.py check          # passes
uv run python manage.py test --noinput # 371 tests, OK
```

(First run hit `database "test_ragtime" does not exist` because the worktree lacked a `.env`. Copied `.env` from the parent project; rerun was clean. The `PostgresTestRunner` plus Django's auto-create handle the test DB once env is in place.)

**Manual smoke test.** Started `uv run uvicorn ragtime.asgi:application --port 8765` in the background, confirmed it logged `Listening to 2 queues:` (`episode_pipeline`, `wikidata_enrichment`). Then ran `uv run python manage.py enrich_entities --limit 1 --retry-failed`. Client logs:

```
(dbos:_queue.py:207) Listening to 0 queues:
(dbos:_dbos.py:680) DBOS launched!
Enqueued 1 entity for Wikidata enrichment.
```

Searched both logs for `Contention detected` and `cannot schedule new futures` — no hits. The only client-side warning was `Failed to start admin server: [Errno 48] Address already in use`, which is unrelated (each DBOS process tries to bind admin port 3001) and was present before this change.

Confirmed `dbos.workflow_status` rows via `psql`:
- `episode-9-run-1` → `episode_pipeline` → `ENQUEUED` (from a `submit_episode` smoke run)
- One `wikidata_enrichment` row → `ENQUEUED` (from `enrich_entities`)

Both rows would have been picked up by uvicorn. Cleaned up the test rows + the test episode after verification.

**Documentation.** Wrote per CLAUDE.md "Documentation > Implementation phase":

- `doc/plans/2026-05-04-dbos-enqueue-only-clients.md`
- `doc/features/2026-05-04-dbos-enqueue-only-clients.md`
- `doc/sessions/2026-05-04-dbos-enqueue-only-clients-planning-session.md`
- `doc/sessions/2026-05-04-dbos-enqueue-only-clients-implementation-session.md` (this file)
- `CHANGELOG.md` entry under `## 2026-05-04`.

No `.env.sample` or configure-wizard changes needed — the fix doesn't introduce, rename, or remove any `RAGTIME_*` variable.

**Commit + PR.** Single commit on `rafacm/dbos-enqueue-only` with the source change, the four doc files, and the changelog entry. Pushed and opened a PR against `main` with `Closes #113`.
