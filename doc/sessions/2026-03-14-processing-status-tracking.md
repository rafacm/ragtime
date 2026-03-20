# Session: Processing Status Tracking

**Date:** 2026-03-14

## Sessions

- Planning session: `ebcf8a85-6dd7-41a6-b9e6-707e1ea8cbbe`
- Implementation session: current

## Summary

Added per-step processing status tracking with `ProcessingRun` and `ProcessingStep` models, enabling retry from the exact failure point instead of reprocessing from scratch. Replaced the two separate admin actions ("Reprocess" and "Retry from last failure") with a single "Reprocess selected episodes..." action that shows an intermediate page where users pick the starting step. Refactored the signal dispatcher to handle all steps uniformly, including SCRAPING.

## Session 1 — Planning

### User
Asked to implement per-step processing status tracking so that failed episodes can be retried from the exact failure point instead of rerunning the entire pipeline.

### Assistant
Explored the existing codebase: `Episode` model with its `Status` choices, the signal-based dispatch in `signals.py`, all 7 step files (`scraper.py`, `downloader.py`, `resizer.py`, `transcriber.py`, `summarizer.py`, `extractor.py`, `resolver.py`), and the admin actions.

Entered plan mode and designed the implementation:
- Two new models: `ProcessingRun` (one per processing attempt) and `ProcessingStep` (one per step within a run)
- A `PIPELINE_STEPS` constant for the ordered step list
- A helper module `episodes/processing.py` with functions for creating runs and recording step progress
- Each step file gets `start_step`/`complete_step`/`fail_step` calls
- Admin gets a `retry_from_failure` action and `ProcessingRunAdmin` with step inline

### User
Approved the plan and asked to implement it.

## Session 2 — Implementation

### User
Provided the full plan and asked to implement it.

### Assistant
Read all files that needed modification (models, signals, admin, all 7 step files, tests). Created the feature branch `feature/processing-status-tracking`.

Implemented in order:
1. Added `PIPELINE_STEPS`, `ProcessingRun`, and `ProcessingStep` models to `episodes/models.py`
2. Created `episodes/processing.py` with helper functions
3. Generated and applied migration `0008_processingrun_processingstep`
4. Modified `signals.py` to call `create_run()` on episode creation
5. Added `start_step`/`complete_step`/`fail_step` calls to all 7 step files, plus `skip_step` in the downloader for the resizing bypass
6. Added `ProcessingRunAdmin`, `ProcessingStepInline`, `ProcessingRunInlineForEpisode`, and both `reprocess` and `retry_from_failure` actions to admin

All 82 tests passed.

### User
Asked how to let users trigger reprocessing from a specific step without a huge action list.

### Assistant
Proposed three approaches: (1) intermediate confirmation page with step dropdown — idiomatic Django admin pattern, (2) dropdown on the episode detail page, (3) separate actions per step. Recommended the intermediate page approach as it keeps the action list short, works for bulk operations, and is standard Django admin.

### User
Asked two follow-up questions: how to show the last failed step on the intermediate page, and whether batch reprocessing would work.

### Assistant
Explained that the intermediate page would show a table with each episode's title, current status, and last failed step (from the most recent failed `ProcessingRun`). The dropdown defaults to the common failed step when all selected episodes failed at the same point. Batch reprocessing works naturally since Django admin actions operate on querysets.

### User
Approved the approach.

### Assistant
Replaced both "Reprocess" and "Retry from last failure" actions with a single "Reprocess selected episodes..." action. Created the intermediate page template at `episodes/templates/admin/episodes/episode/reprocess.html`. Updated the admin test to cover the two-step flow. All 82 tests passed.

### User
Tested reprocessing but no Processing Runs were created.

### Assistant
Investigated — migration was applied, so the issue was in the template. The intermediate form was missing the `action` and `_selected_action` hidden fields, so Django admin didn't route the second POST back to the `reprocess` action. Fixed the template to include these hidden fields. Confirmed fix worked.

### User
Asked why SCRAPING needed special handling in the admin action.

### Assistant
The asymmetry existed because the signal only dispatched SCRAPING on `created=True`, not on status updates. Added SCRAPING to the status-change dispatch block in `signals.py`, removed the `async_task` import and special case from `admin.py`, and updated the test. All steps now dispatch uniformly through the signal. All 82 tests passed.

### User
Confirmed it works. Asked to change the ProcessingRun list page first column to show "Episode (Run)" with episode title and run ID.

### Assistant
Added an `episode_run` display method to `ProcessingRunAdmin` that shows `"{episode} ({run_id})"` with column header "Episode (Run)".

### User
Asked to create a PR.

### Assistant
Created plan doc, feature doc, session transcript, updated README, committed all changes, and opened a PR.
