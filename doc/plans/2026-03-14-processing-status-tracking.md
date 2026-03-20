# Processing Status Tracking

**Date:** 2026-03-14

## Context

Currently, episode processing status is a single `status` field on the `Episode` model. When a step fails and is retried, the only option is "reprocess from scratch" — rerunning all steps including expensive LLM calls (summarization, extraction, resolution) that already succeeded. This wastes money and time. We need per-step tracking so we can retry from the exact failure point.

## New Models (`episodes/models.py`)

### `ProcessingRun`
One per processing attempt for an episode. Fields:
- `episode` — FK to Episode
- `status` — running / completed / failed
- `started_at` — auto_now_add
- `finished_at` — nullable
- `resumed_from_step` — blank means full run; otherwise the step name we resumed from

### `ProcessingStep`
One per step within a run. Fields:
- `run` — FK to ProcessingRun
- `step_name` — CharField matching Episode.Status values (scraping, downloading, etc.)
- `status` — pending / running / completed / failed / skipped
- `started_at` — nullable
- `finished_at` — nullable
- `error_message` — blank default
- Unique constraint on (run, step_name)

### `PIPELINE_STEPS` constant
Ordered list of the 8 current processing steps: `[SCRAPING, DOWNLOADING, RESIZING, TRANSCRIBING, SUMMARIZING, EXTRACTING, RESOLVING, EMBEDDING]`.

## New Helper Module (`episodes/processing.py`)

Functions that step functions call to record progress:

| Function | Purpose |
|---|---|
| `create_run(episode, resume_from="")` | Create a `ProcessingRun` + all `ProcessingStep` records. Steps before `resume_from` are pre-marked SKIPPED. |
| `get_active_run(episode)` | Return the most recent RUNNING run (or None). |
| `start_step(episode, step_name)` | Mark step as RUNNING, set `started_at`. |
| `complete_step(episode, step_name)` | Mark step as COMPLETED, set `finished_at`. If last step, mark run COMPLETED. |
| `fail_step(episode, step_name, error_message)` | Mark step FAILED, mark run FAILED, set `finished_at` on both. |
| `skip_step(episode, step_name)` | Mark step SKIPPED (used by downloader when file doesn't need resizing). |

All helpers are no-ops if no active run exists (graceful degradation).

## Changes to Step Functions

Each of the 7 step files gets 3 additions (same pattern everywhere):

1. **After status validation**: call `start_step(episode, <STEP>)`
2. **On success** (before saving next status): call `complete_step(episode, <STEP>)`
3. **On failure** (in except block, after existing error handling): call `fail_step(episode, <STEP>, str(exc))`

Files: `scraper.py`, `downloader.py`, `resizer.py`, `transcriber.py`, `summarizer.py`, `extractor.py`, `resolver.py`

**Special case — `downloader.py`**: When file is ≤ 25MB and skips resizing, call `skip_step(episode, Episode.Status.RESIZING)` before setting status to TRANSCRIBING.

The `Episode.status` and `Episode.error_message` fields continue to work as before — they remain the quick-glance current state.

## Changes to Signals (`episodes/signals.py`)

Two changes:
1. When an episode is created with PENDING status, call `create_run(episode)` before queuing the scraper task.
2. Add SCRAPING to the status-change dispatch block so all steps are dispatched uniformly via `episode.save(update_fields=["status", ...])`.

## Changes to Admin (`episodes/admin.py`)

### New admin classes
- **`ProcessingRunAdmin`** — registered for `ProcessingRun`. Read-only, with `ProcessingStepInline` showing all steps. No add permission. First column shows "Episode (Run)" with episode title and run ID.
- **`ProcessingStepInline`** — TabularInline on ProcessingRunAdmin. Read-only.
- **`ProcessingRunInlineForEpisode`** — TabularInline on EpisodeAdmin. Shows runs with `show_change_link=True` so admins can click through to see step details.

### Unified reprocess action with intermediate page
Replaces both "Reprocess" and "Retry from last failure" with a single **"Reprocess selected episodes..."** action that:
1. Shows an intermediate confirmation page with a table of selected episodes (title, current status, last failed step)
2. Provides a dropdown to pick the starting step (defaults to the common failed step if all selected episodes failed at the same step)
3. On submit, creates a `ProcessingRun` and sets the episode status to trigger the signal

### Updated inlines
Add `ProcessingRunInlineForEpisode` to `EpisodeAdmin.inlines`.

## Files Modified

| File | Change |
|---|---|
| `episodes/models.py` | Add `PIPELINE_STEPS`, `ProcessingRun`, `ProcessingStep` |
| `episodes/processing.py` | **New.** Helper functions for run/step management |
| `episodes/signals.py` | Add `create_run` call on episode creation, add SCRAPING to dispatch |
| `episodes/scraper.py` | Add start/complete/fail step calls |
| `episodes/downloader.py` | Add start/complete/fail/skip step calls |
| `episodes/resizer.py` | Add start/complete/fail step calls |
| `episodes/transcriber.py` | Add start/complete/fail step calls |
| `episodes/summarizer.py` | Add start/complete/fail step calls |
| `episodes/extractor.py` | Add start/complete/fail step calls |
| `episodes/resolver.py` | Add start/complete/fail step calls |
| `episodes/admin.py` | Add ProcessingRunAdmin, inlines, unified reprocess action with intermediate page |
| `episodes/templates/admin/episodes/episode/reprocess.html` | **New.** Intermediate page template |
| `episodes/tests/test_admin.py` | Update reprocess tests for two-step flow |
| `episodes/migrations/` | New migration for ProcessingRun and ProcessingStep |
