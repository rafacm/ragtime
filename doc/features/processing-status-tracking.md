# Feature: Processing Status Tracking

## Problem

Episode processing had a single `status` field on the `Episode` model. When a step failed, the only recovery option was "reprocess from scratch" — rerunning all steps including expensive LLM calls (summarization, extraction, resolution) that already succeeded. There was no way to know which step failed or to retry from the exact failure point.

## Changes

- **`episodes/models.py`**: Added `PIPELINE_STEPS` constant (ordered list of 8 processing steps), `ProcessingRun` model (one per processing attempt, tracks running/completed/failed status and optional `resumed_from_step`), and `ProcessingStep` model (one per step within a run, tracks pending/running/completed/failed/skipped status with timestamps and error messages). Unique constraint on (run, step_name).

- **`episodes/processing.py`** (new): Helper functions that step functions call to record progress — `create_run()`, `get_active_run()`, `start_step()`, `complete_step()`, `fail_step()`, `skip_step()`. All helpers are no-ops if no active run exists, ensuring graceful degradation.

- **`episodes/signals.py`**: Calls `create_run(instance)` when a new PENDING episode is created. Added SCRAPING to the status-change dispatch block so all steps (including scraping) are dispatched uniformly via the signal — no special-casing needed in admin or elsewhere.

- **7 step files** (`scraper.py`, `downloader.py`, `resizer.py`, `transcriber.py`, `summarizer.py`, `extractor.py`, `resolver.py`): Each gets `start_step()` after status validation, `complete_step()` before saving the next status, and `fail_step()` in error handlers. The downloader additionally calls `skip_step(RESIZING)` when the file doesn't need resizing.

- **`episodes/admin.py`**: Replaced "Reprocess" and "Retry from last failure" actions with a single **"Reprocess selected episodes..."** action that shows an intermediate confirmation page. The page lists selected episodes with their current status and last failed step, and provides a dropdown to pick the starting step. The dropdown defaults to the common failed step when all selected episodes failed at the same point. Added `ProcessingRunAdmin` (read-only, with step inline), `ProcessingRunInlineForEpisode` on EpisodeAdmin with `show_change_link=True`, and an "Episode (Run)" column on the ProcessingRun list page.

- **`episodes/templates/admin/episodes/episode/reprocess.html`** (new): Intermediate page template for the reprocess action.

- **`episodes/tests/test_admin.py`**: Updated reprocess test to cover the two-step flow (intermediate page display + execution).

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `ProcessingRun.status` choices | running, completed, failed | Minimal set to track run lifecycle |
| `ProcessingStep.status` choices | pending, running, completed, failed, skipped | Skipped needed for resumed runs and resizing bypass |
| `PIPELINE_STEPS` | 8 steps (scraping through embedding) | Matches existing Episode.Status values used by the pipeline |
| Graceful degradation | All helpers are no-ops without active run | Existing code paths work unchanged if no run was created |

## Verification

```bash
# Run all episode tests (82 tests)
uv run python manage.py test episodes

# Manual verification:
# 1. Create an episode in admin -> verify ProcessingRun and ProcessingSteps created
# 2. On a FAILED episode, use "Reprocess selected episodes..." -> pick failed step -> verify only that step and later steps run
# 3. Use "Reprocess selected episodes..." -> pick "Scraping" -> verify full reprocess with new run
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `PIPELINE_STEPS`, `ProcessingRun`, `ProcessingStep` models |
| `episodes/processing.py` | New — helper functions for run/step management |
| `episodes/signals.py` | Added `create_run` on episode creation, added SCRAPING to dispatch |
| `episodes/scraper.py` | Added start/complete/fail step calls |
| `episodes/downloader.py` | Added start/complete/fail/skip step calls |
| `episodes/resizer.py` | Added start/complete/fail step calls |
| `episodes/transcriber.py` | Added start/complete/fail step calls |
| `episodes/summarizer.py` | Added start/complete/fail step calls |
| `episodes/extractor.py` | Added start/complete/fail step calls |
| `episodes/resolver.py` | Added start/complete/fail step calls |
| `episodes/admin.py` | Added ProcessingRunAdmin, inlines, unified reprocess action with intermediate page |
| `episodes/templates/admin/episodes/episode/reprocess.html` | New — intermediate page template |
| `episodes/tests/test_admin.py` | Updated reprocess tests for two-step flow |
| `episodes/migrations/0008_processingrun_processingstep.py` | New migration |
