# Migrate from Django Q2 to DBOS Transact

**Date:** 2026-04-19

## Context

RAGtime's 10-step ingestion pipeline uses Django Q2 for async task dispatch. The pipeline is driven by Django signals: each task function updates the episode status, which triggers a `post_save` signal that dispatches the next `async_task()`. On top of this, a custom orchestration layer (`processing.py`, `recovery.py`, `events.py`) tracks state via `ProcessingRun`/`ProcessingStep`/`PipelineEvent` models and handles failure recovery.

This migration replaces Django Q2 with DBOS Transact, which provides durable workflow execution backed by PostgreSQL. This is a stepping stone toward a Pydantic AI agent-based architecture — DBOS has a Pydantic AI integration that adds persistence to agents.

## Design Decisions

1. **One DBOS workflow replaces the signal chain.** A single `@DBOS.workflow()` function calls all 8 steps in order. The `post_save` signal only starts the workflow on episode creation.
2. **ProcessingRun/ProcessingStep models stay.** They're the audit trail (application layer). DBOS checkpointing is the runtime layer.
3. **Task functions stay unchanged.** `scrape_episode()`, `download_episode()`, etc. keep their current signatures and internal logic.
4. **Recovery chain stays, with one update.** `resume_pipeline()` starts a DBOS workflow instead of relying on the signal.
5. **DBOS configured programmatically.** No `dbos-config.yaml` — reuse Django DATABASES credentials.

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Replace `django-q2` with `dbos` |
| `episodes/workflows.py` | Create | DBOS workflow + step definitions |
| `episodes/signals.py` | Modify | Replace `async_task` with `DBOS.start_workflow` |
| `episodes/admin.py` | Modify | Replace `async_task`, move recovery task to workflows |
| `episodes/agents/resume.py` | Modify | Use `DBOS.start_workflow` for pipeline resume |
| `episodes/apps.py` | Modify | Add `DBOS.launch()` initialization |
| `ragtime/settings.py` | Modify | Remove `django_q` from INSTALLED_APPS and Q_CLUSTER |
| `episodes/tests/test_signals.py` | Modify | Rewrite for new signal behavior |
| 13 other test files | Modify | Mechanical mock target replacement |

## Verification

1. `uv sync` — DBOS installs correctly
2. `uv run python manage.py migrate` — DBOS creates its system tables
3. `uv run python manage.py test` — all 274 tests pass
4. Manual: create episode via admin → verify pipeline completes
5. Manual: reprocess a failed episode from a specific step
