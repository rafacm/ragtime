# DBOS Migration Implementation Session

**Date:** 2026-04-19

**Session ID:** 2d844f5c-cf29-47af-8019-7c0b4a3e2efa

## Summary

Implemented the migration from Django Q2 to DBOS Transact. Created the DBOS workflow module, updated signal dispatch, admin actions, recovery resume, DBOS initialization, settings, and all 14 test files. Fixed two test failures related to changed dispatch semantics. All 274 tests pass.

### User

(Plan approved)

### Assistant

Created feature branch `feature/dbos-migration` off main. Also converted CLAUDE.md from symlink to standalone file with `@AGENTS.md` reference (per user request earlier in session).

Checked DBOS package on PyPI: v2.18.0, supports Python >=3.10. Fetched DBOS Django integration docs — confirmed initialization pattern: `DBOS(config=dbos_config)` then `DBOS.launch()` in `AppConfig.ready()`, with `--noreload` requirement for dev server.

Implementation followed the plan's migration order:

**Step 1: pyproject.toml** — Replaced `django-q2>=1.7,<2` with `dbos>=2.18,<3`.

**Step 2: episodes/workflows.py** — Created new file with:
- `process_episode()` workflow: sequences all 8 pipeline steps, checks run status after each
- `create_run_step()`, `execute_pipeline_step()`, `is_run_still_active()` as DBOS steps
- `run_agent_recovery()` workflow + `execute_agent_recovery()` step (moved from admin.py's `_run_agent_recovery_task`)

**Step 3: episodes/apps.py** — Added `_init_dbos()` method that builds PostgreSQL URL from Django DATABASES config, initializes DBOS. Added `"test" in sys.argv` guard to skip DBOS during tests.

**Step 4: episodes/signals.py** — Replaced entire `queue_next_step` handler. Now only starts workflow on `created=True` + PENDING. All status-change dispatch removed (workflow handles sequencing).

**Step 5: episodes/admin.py** — Replaced `async_task` import with DBOS. Updated `_execute_reprocess` to use `DBOS.start_workflow(process_episode, ...)` — removed `create_run()` call (workflow handles it) and scraping special-case. Updated `retry_agent_recovery` to use `DBOS.start_workflow(run_agent_recovery, ...)`. Deleted `_run_agent_recovery_task` function. Removed unused `create_run` import.

**Step 6: episodes/agents/resume.py** — Removed `create_run` import, added DBOS import. Updated `_resume_from_scraping` and `_resume_from_downloading` to call `DBOS.start_workflow(process_episode, ...)` instead of `create_run()` + signal dispatch.

**Step 7: ragtime/settings.py** — Removed `django_q` from INSTALLED_APPS and entire `Q_CLUSTER` block.

**Step 8: Tests** — `test_signals.py` fully rewritten (3 tests: workflow start on creation, no-dispatch on update, no-dispatch on status change). Mechanical sed replacement of `episodes.signals.async_task` → `episodes.signals.DBOS` and `episodes.admin.async_task` → `episodes.admin.DBOS` across 13 other test files. Updated `test_admin.py` assertions for DBOS.start_workflow, imported recovery from workflows. Rewrote `test_agent_resume.py` to verify DBOS.start_workflow instead of ProcessingRun creation.

**Step 9: Docs** — Updated AGENTS.md (architecture, tech choices, runserver command), README.md (removed qcluster, updated tech stack), doc/README.md (pipeline description). Removed stale Q_CLUSTER comment from transcriber.py.

### User

(Ran uv sync — DBOS installed, Django Q2 removed)

### Assistant

Ran `uv run python manage.py test --verbosity 2`. First run failed: DBOS tried to connect to PostgreSQL during Django setup. Fixed by adding `"test" in sys.argv` guard in `_init_dbos()`.

Second run failed: PostgreSQL not running (Docker not started).

User started PostgreSQL via `docker compose up -d postgres`. Ran tests again — 2 failures in `test_scraper.py`:

1. `test_success_queues_download_task` — asserted old `async_task` call for download dispatch. Fixed: renamed to `test_success_sets_downloading_status`, now checks episode.status instead of dispatch call.

2. `test_incomplete_metadata_does_not_overwrite_recovery_status` — `fail_step` was a no-op because no ProcessingRun existed (old signal created it, new workflow creates it but was mocked). Fixed: added `create_run(episode)` call before scraping, and added `@patch("episodes.agents.resume.DBOS")` mock.

Final run: all 274 tests pass.

### User

Have we removed the signals then?

### Assistant

Clarified: signals are not removed. The `post_save` signal still starts the workflow on episode creation. The `step_completed` and `step_failed` custom signals still power the audit trail and recovery chain. What was removed is the status-change dispatch logic (the 8-way if/elif chain in `queue_next_step`), because the DBOS workflow now handles step sequencing internally.

### User

Create a PR

### Assistant

Created plan, feature, and session documentation. Committed and pushed. Created PR #94.

### User

/pr-review-comments-process

### Assistant

Reviewed 3 PR review comments from rafacm:

1. **`episodes/apps.py:39` — URL-encode DB credentials**: `quote_plus()` needed on user/password for special characters. Severity: medium.
2. **`episodes/apps.py:21` — Gate DBOS init to server entrypoints**: `_init_dbos()` runs for every Django command (`check`, `makemigrations`, `shell`), which is a regression — those commands previously didn't need PostgreSQL. Severity: medium.
3. **`episodes/workflows.py:44` — Detect silent step no-op**: If a step function returns early (status mismatch), `is_run_still_active` still returns True, so the workflow silently proceeds. Need to verify step actually completed. Severity: medium.

### User

implement your suggestions

### Assistant

Applied all three fixes:

**Fix 1**: Added `quote_plus()` on `db["USER"]` and `db["PASSWORD"]` in `episodes/apps.py`.

**Fix 2**: Replaced `"test" in sys.argv` guard with a whitelist approach — `_DBOS_COMMANDS = {"runserver"}` — so only server entrypoints initialize DBOS. Commands like `migrate`, `check`, `shell`, `makemigrations` skip DBOS entirely.

**Fix 3**: Added `did_step_complete()` and `mark_run_failed()` step functions in `episodes/workflows.py`. After `execute_pipeline_step()`, if the run is still active but the step's `ProcessingStep` record didn't transition to `COMPLETED`, the run is marked `FAILED` with a log message and the workflow returns.

All 274 tests pass.

### User

I tested locally the ingestion of a podcast episode and I can see this error [stack trace showing `AssertionError` at `dbos/_context.py:183` from `DBOS.start_workflow` called via `resume.py:104` inside the step-failed signal chain].

### Assistant

Diagnosed the root cause: the `step_failed` Django signal fires synchronously inside `fail_step`, which runs inside the `execute_pipeline_step` DBOS step. The recovery chain (`handle_step_failure` → `AgentStrategy.attempt` → `resume_pipeline`) therefore executes in a DBOS step context, where `DBOS.start_workflow` is forbidden (the assertion `cur_ctx.is_workflow() # Not in a step` fires).

Proposed two options:
- **A**: Spawn a thread inside `resume_pipeline` that calls `start_workflow` outside the DBOS context — minimal patch but has a durability hole on crash.
- **B**: Stop doing workflow dispatch inside the step. Have `resume_pipeline` only update persistent state (episode.status); have `process_episode` detect the recovery after the step returns and call `start_workflow` itself from workflow context (where it's allowed).

### User

Let's go for option B.

### Assistant

Implemented option B:

- `episodes/agents/resume.py`: removed all `DBOS.start_workflow(...)` calls. The module now only updates `episode.status` (to `DOWNLOADING` or `TRANSCRIBING`) and the audio file/URL fields. Updated the module docstring to document the new contract.
- `episodes/workflows.py`:
  - Added `get_pending_resume_step(episode_id, failed_step)` DBOS step. Returns `episode.status` if it's a pipeline step strictly after the failed step (the recovery chain's signal), else empty string.
  - Rewrote `process_episode` loop: after each step, if the run is active and the step completed, continue. Otherwise, check `get_pending_resume_step`; if it returns a step, `DBOS.start_workflow(process_episode, episode_id, resume_step)` from workflow context (allowed) and return. If no resume intent, mark run FAILED (if not already) and return.
  - Added `get_pipeline_event_step` helper. Updated `run_agent_recovery` workflow (admin-triggered path) to use the same pattern: read the failed step, run the recovery step, then dispatch a new `process_episode` workflow if recovery succeeded.
- Tests: removed `@patch("episodes.agents.resume.DBOS")` decorators and `mock_dbos.start_workflow.assert_called_once_with(...)` assertions from `test_agent_resume.py` (2 tests) and `test_scraper.py` (1 test). Renamed `test_sets_audio_url_and_starts_workflow` → `test_sets_audio_url_and_marks_episode_for_downloading` and `test_saves_file_and_starts_workflow` → `test_saves_file_and_marks_episode_for_transcribing`.

All 274 tests pass.
