# DBOS Enqueue-Only Clients — Implementation Session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Implemented the plan in `doc/plans/2026-05-04-dbos-enqueue-only-clients.md` on branch `rafacm/dbos-enqueue-only`. Single-file source change: `episodes/apps.py:_init_dbos` now distinguishes worker entrypoints (`uvicorn`, `runserver`) from client management commands (`submit_episode`, `enrich_entities`). Clients call `DBOS.listen_queues([])` immediately before `DBOS.launch()` so the dispatcher iterates over zero application queues — eliminating both the "Contention detected" warning and the "cannot schedule new futures after shutdown" race at exit.

Full test suite (371 tests) passes. Manual smoke test confirmed the behaviour: client logs `Listening to 0 queues:` and exits cleanly while uvicorn runs alongside.

## Detailed conversation

This session was orchestrated by a parent agent acting on behalf of the user via Claude Code's Agent tool with `isolation: worktree`. No direct user-to-implementation-agent messages occurred. The parent-agent's launching prompt — which serves as the de-facto user message for this session per AGENTS.md's "Agent-orchestrated sessions" convention — is reproduced verbatim below.

### Parent agent (orchestrator)

> You are working on issue #113 in the rafacm/ragtime repo: "manage.py enrich_entities should be a DBOS client, not a worker".
>
> ## Read first
> - `CLAUDE.md` and `AGENTS.md` (project docs requirements, branching rules)
> - The full issue: run `gh issue view 113`
> - Issue #108 / PR #109 for context on the DBOS queue restructure
>
> ## Step 0 — Branching
> Per AGENTS.md, confirm we are on `main` and pull latest. Create a branch named `rafacm/dbos-enqueue-only` off `main`.
>
> ## Step 1 — Staleness check
> The issue may already be partially or fully implemented. Before doing any work:
> 1. Read `episodes/apps.py` — look at `_init_dbos` and `_DBOS_COMMANDS`. Has the worker/client distinction already been introduced?
> 2. Read `episodes/management/commands/enrich_entities.py`
> 3. Read `episodes/management/commands/submit_episode.py`
> 4. Check git log: `git log --oneline --all -- episodes/apps.py | head -20`
>
> If the issue is already resolved, stop and report.
>
> ## Step 2 — Implementation (per issue's recommended Option 1)
> 1. In `episodes/apps.py:_init_dbos`, distinguish "worker" commands (uvicorn, runserver) from "client" commands (`submit_episode`, `enrich_entities`). For client commands: instantiate DBOS + import workflow modules so `@DBOS.workflow` registrations run, but skip `DBOS.launch()`.
> 2. Verify `Queue.enqueue` works without `launch()` — read DBOS source under the project venv (`uv run python -c "import dbos; print(dbos.__file__)"` then inspect `_queue.py`). If `enqueue` truly does not need `launch()`, proceed. If it does, fall back to Option 2 (brief drain loop).
> 3. Apply the same pattern to `submit_episode` (issue acceptance criterion).
>
> ## Step 3 — Verification
> - Run `uv run python manage.py test` (full suite)
> - Run `uv run python manage.py check`
> - If feasible, manually verify the no-warning behavior: start uvicorn in one shell, run `manage.py enrich_entities` in another, confirm no "Contention detected" or "cannot schedule new futures after shutdown" log lines. If this requires running a DB and is impractical in a worktree, document the manual test steps and skip the live test — but note clearly in your report what you didn't run.
>
> ## Step 4 — Documentation
> Follow CLAUDE.md's "Documentation > Implementation phase" — feature doc in `doc/features/`, session transcripts in `doc/sessions/`, changelog entry. Date prefix `2026-05-04-`.
>
> ## Step 5 — PR
> - Push and `gh pr create --base main` (rebase strategy)
> - "Closes #113" in body
> - PR title: short
>
> ## Reporting
> At the end report: (a) staleness verdict, (b) confirmed Option 1 works without launch() or fell back to Option 2 with reason, (c) files changed, (d) PR URL, (e) what you did and didn't manually verify. Under 250 words.

### Assistant (implementation agent)

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

### Follow-up — agent-orchestrated transcript convention (PR #136)

After the initial PR was opened, the codex review on PR #131 flagged two failing AI checks. One of them — Feature PR Documentation Bundle — was failing on (a) duplicated session UUIDs across the planning and implementation transcripts, and (b) summarized rather than verbatim user content. PR #136 then merged a policy clarification to AGENTS.md and `.ai-checks/feature-pr-docs.md` recognizing **agent-orchestrated sessions**: when a parallel implementation agent has no direct user-to-implementation-agent messages, the transcript may use `### Parent agent (orchestrator)` headings instead of `### User`, provided the parent-agent's launching prompt is reproduced verbatim and the session is explicitly declared as agent-orchestrated at the top of `## Detailed conversation`.

A follow-up commit on this branch rebases onto the post-#136 main and updates both transcripts to comply: the planning transcript now contains verbatim user messages from the parent conversation that authorized this work; this implementation transcript declares itself agent-orchestrated and reproduces the parent agent's launching prompt verbatim under the `### Parent agent (orchestrator)` heading. Session UUID values were also audited — both files now use the honest `unavailable` placeholder (the original duplicated UUID was fabricated, not a real Claude Code session ID, and the real UUIDs are not recoverable). The Comment Discipline AI check (long explanatory blocks in `episodes/apps.py`) remains failing and is intentionally deferred to a separate follow-up PR.
