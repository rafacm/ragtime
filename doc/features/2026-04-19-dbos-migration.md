# DBOS Transact Migration

**Date:** 2026-04-19

## Problem

The ingestion pipeline used Django Q2 for async task dispatch via a signal-driven chain: each task set the next episode status, triggering a `post_save` signal that called `async_task()` for the next step. This required a separate `qcluster` worker process and had no built-in crash recovery or workflow checkpointing. The architecture was also a dead end for the planned Pydantic AI agent migration — Django Q2 has no concept of durable workflows.

## Changes

Replaced Django Q2 with DBOS Transact, which provides PostgreSQL-backed durable workflow execution. A single `@DBOS.workflow()` function in `episodes/workflows.py` now sequences all 8 pipeline steps, with each step checkpointed in PostgreSQL. On crash or restart, the workflow resumes from the last completed step automatically.

The signal-driven dispatch chain (status change → `async_task`) was removed. The `post_save` signal now only starts the workflow on episode creation. Status changes still happen (for the admin UI) but no longer drive dispatch.

The custom orchestration layer (`ProcessingRun`/`ProcessingStep`/`PipelineEvent` models, recovery chain) is preserved as the audit trail.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| DBOS version | `>=2.18,<3` | Latest stable with Django integration |
| `system_database_url` | Built from Django `DATABASES["default"]` | Single source of truth, no config duplication |
| DBOS init guard | Whitelist of commands (`runserver`) | Only server entrypoints need a live DBOS connection; prevents `migrate`, `check`, `shell`, etc. from requiring PostgreSQL |
| `--noreload` for runserver | Required | DBOS cannot handle Django's auto-reloader restarting the process |

## Verification

```bash
docker compose up -d postgres
uv run python manage.py test --verbosity 2   # 274 tests pass
uv run python manage.py runserver --noreload  # Dev server with DBOS
```

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Replace `django-q2>=1.7,<2` with `dbos>=2.18,<3` |
| `episodes/workflows.py` | New: DBOS workflow (`process_episode`) + step functions + `run_agent_recovery` workflow + silent no-op detection (`did_step_complete`/`mark_run_failed`) |
| `episodes/signals.py` | Replace `async_task` dispatch chain with single `DBOS.start_workflow` on creation |
| `episodes/admin.py` | Replace `async_task` calls with `DBOS.start_workflow`; remove `_run_agent_recovery_task` (moved to workflows); remove unused `create_run` import |
| `episodes/agents/resume.py` | Replace `create_run()` + signal dispatch with `DBOS.start_workflow()` |
| `episodes/apps.py` | Add `_init_dbos()` — programmatic DBOS config from Django DATABASES, gated to server entrypoints only, URL-encodes credentials |
| `ragtime/settings.py` | Remove `django_q` from INSTALLED_APPS; remove `Q_CLUSTER` config |
| `episodes/transcriber.py` | Remove stale `Q_CLUSTER` comment on `FFMPEG_TIMEOUT` |
| `AGENTS.md` | Update architecture and tech choices; add `--noreload` to runserver command |
| `CLAUDE.md` | Convert from symlink to standalone file referencing `@AGENTS.md` |
| `README.md` | Replace `qcluster` command with `runserver --noreload`; update tech stack entry |
| `doc/README.md` | Update pipeline description: DBOS workflow replaces signal-driven dispatch |
| `episodes/tests/test_signals.py` | Rewrite: test workflow start on creation, no-dispatch on status change |
| `episodes/tests/test_admin.py` | Update mock targets and assertions for DBOS; import recovery from workflows |
| `episodes/tests/test_agent_resume.py` | Rewrite: verify `DBOS.start_workflow` instead of `ProcessingRun` creation |
| `episodes/tests/test_scraper.py` | Fix 2 tests: update signal test, add `create_run()` for recovery test |
| 10 other test files | Mechanical `async_task` → `DBOS` mock target replacement |
