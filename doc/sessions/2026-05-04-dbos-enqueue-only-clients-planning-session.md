# DBOS Enqueue-Only Clients — Planning Session

**Date:** 2026-05-04

**Session ID:** 5b5b2169-5e23-4e06-852f-56035beab570

## Summary

Triage of issue #113. Confirmed the bug from prior context (PR #109 / issue #108 work surfaced both the contention warning and the shutdown error). Three options laid out in the issue body. Selected Option 1 ("don't launch from clients") as the architectural fix, with a fall-back to Option 2 (brief drain loop) if `Queue.enqueue` turned out to require `launch()`. Investigation showed pure Option 1 doesn't work — `DBOS._sys_db` raises if not launched — so the implementation refines Option 1 by using `DBOS.listen_queues([])` to launch the client with zero application queues attached. Same posture, working knob.

## Detailed conversation

### User

> manage.py enrich_entities should be a DBOS client, not a worker
>
> [issue #113 body, full text — context, observed errors, three options, recommendation, acceptance criteria]

### Assistant

Read the issue. Confirmed the symptoms by grepping the project: `episodes/apps.py:_init_dbos` indeed listed `enrich_entities` and `submit_episode` in `_DBOS_COMMANDS`, calling `DBOS.launch()` for both. Looked at the two affected commands — both are pure enqueuers (`enqueue_entities(ids)` and `Episode.objects.get_or_create` triggering a `post_save` signal that enqueues `process_episode`).

Considered the three options:

- **Option 1 (recommended): split worker vs client; clients skip `launch()`.** Architectural; eliminates both noises. Risk flagged in the issue: does `Queue.enqueue` actually work without `launch()`?
- **Option 2: brief drain loop.** Cleaner shutdown but keeps compute moving in the wrong process; doesn't address contention.
- **Option 3: document the warnings and move on.** Cheapest; loud forever.

Picked Option 1. Proceeded to validate the assumption.

Investigation in `.venv/lib/python3.13/site-packages/dbos/`:

- `_queue.py:Queue.enqueue` → `start_workflow(execute_workflow=False)`. Doesn't directly start a dispatcher.
- `_core.py:start_workflow` calls `_init_workflow(...)` which goes through `dbos._sys_db`.
- `_dbos.py`: `_sys_db` is a property that raises `DBOSException("System database accessed before DBOS was launched")` if `_launched` is false. The system database engine is created inside `launch()` itself (line 548 `self._sys_db_field = SystemDatabase.create(...)`).

Conclusion: pure "skip launch" does NOT work — the first `Queue.enqueue` raises.

Looked for a knob that lets DBOS launch but skip dispatching from our queues. Found `DBOS.listen_queues(queues)` at `_dbos.py:2925` — must be called before launch; sets `_listening_queues` which is consulted by the queue manager thread at `_queue.py:200-205`:

```python
if dbos._listening_queues is not None:
    listening_queues = dbos._listening_queues
else:
    listening_queues = list(dbos._registry.queue_info_map.values())
```

With `listen_queues([])`, the queue manager iterates over an empty list (plus the always-present internal queue — unrelated to ours). No contention thread ever runs against `episode_pipeline` or `wikidata_enrichment`, and the local executor never receives one of our workflows, so no "cannot schedule new futures after shutdown" race at exit.

This is a refinement of Option 1 — same architectural posture (clients don't dispatch from our queues) — implemented through DBOS's official mechanism. No fall-back to Option 2 needed.

Plan to implement:

1. `episodes/apps.py:_init_dbos`: split `_DBOS_COMMANDS` into `_WORKER_COMMANDS = {"runserver"}` and `_CLIENT_COMMANDS = {"submit_episode", "enrich_entities"}`. Compute `is_worker` and `is_client`. Skip if neither.
2. After constructing `DBOS(config=…)`, if client-only, call `DBOS.listen_queues([])`. Then `DBOS.launch()` unconditionally.
3. No changes to `enrich_entities.py`, `submit_episode.py`, signals, or workflows.

Verification: full test suite + manual smoke test (uvicorn in one shell, client in another, watch the logs).
