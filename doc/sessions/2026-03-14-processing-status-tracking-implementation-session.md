# Session: Processing Status Tracking — Implementation

**Date:** 2026-03-14
**Session ID:** b64c02cc-642e-4cfe-94e9-6d3e1d2bd549

## Summary

*(No summary available)*

## Conversation

### User

[Request interrupted by user for tool use]

Implement the following plan:

# Processing Status Tracking

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

## New Helper Module (`episodes/processing.py` — new file)

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

One addition: when an episode is created with PENDING status, call `create_run(episode)` before queuing the scraper task. No other signal changes needed — `get_active_run()` finds the current run without needing a run_id passed through.

## Changes to Admin (`episodes/admin.py`)

### New admin classes
- **`ProcessingRunAdmin`** — registered for `ProcessingRun`. Read-only, with `ProcessingStepInline` showing all steps. No add permission.
- **`ProcessingStepInline`** — TabularInline on ProcessingRunAdmin. Read-only.
- **`ProcessingRunInlineForEpisode`** — TabularInline on EpisodeAdmin. Shows runs with `show_change_link=True` so admins can click through to see step details.

### New action: `retry_from_failure`
- Filters queryset to FAILED episodes only
- Finds the last failed run's failed step
- Creates a new run with `resume_from=<failed_step>`
- Sets episode status to the failed step's status value (triggers signal → queues the task)
- Clears `error_message`

### Modified action: `reprocess`
- Now calls `create_run(episode)` (full run, no resume_from) before setting status to SCRAPING

### Updated inlines
Add `ProcessingRunInlineForEpisode` to `EpisodeAdmin.inlines`.

## Files Modified

| File | Change |
|---|---|
| `episodes/models.py` | Add `PIPELINE_STEPS`, `ProcessingRun`, `ProcessingStep` |
| `episodes/processing.py` | **New.** Helper functions for run/step management |
| `episodes/signals.py` | Add `create_run` call on episode creation |
| `episodes/scraper.py` | Add start/complete/fail step calls |
| `episodes/downloader.py` | Add start/complete/fail/skip step calls |
| `episodes/resizer.py` | Add start/complete/fail step calls |
| `episodes/transcriber.py` | Add start/complete/fail step calls |
| `episodes/summarizer.py` | Add start/complete/fail step calls |
| `episodes/extractor.py` | Add start/complete/fail step calls |
| `episodes/resolver.py` | Add start/complete/fail step calls |
| `episodes/admin.py` | Add ProcessingRunAdmin, inlines, retry_from_failure action, modify reprocess |
| `episodes/migrations/` | New migration for ProcessingRun and ProcessingStep |

## Implementation Order

1. Models + PIPELINE_STEPS constant
2. `episodes/processing.py` helpers
3. Generate + apply migration
4. Modify `signals.py`
5. Modify all 7 step functions (independent of each other — can be parallelized)
6. Modify `admin.py`
7. Run tests, verify

## Verification

1. `uv run python manage.py makemigrations && uv run python manage.py migrate`
2. `uv run python manage.py test episodes` — existing tests pass
3. Manual: create an episode in admin → verify ProcessingRun and ProcessingSteps are created and updated as pipeline progresses
4. Manual: on a FAILED episode, use "Retry from last failure" action → verify only the failed step and subsequent steps run, prior steps show SKIPPED
5. Manual: use "Reprocess" → verify a new full run is created


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/ebcf8a85-6dd7-41a6-b9e6-707e1ea8cbbe.jsonl

### Assistant

I'll start by reading the existing files I need to modify.

Now let me read the step files.

Now let me create the branch and start implementing. First, let me check existing tests and migrations.

Now let me implement everything. Starting with models, then processing helpers, then the step files.

**Step 1: Add models + PIPELINE_STEPS constant**

**Step 2: Create `episodes/processing.py`**

**Step 3: Generate migration**

**Step 4: Modify `signals.py`**

**Step 5: Modify all 7 step functions**

Now I need to add `complete_step` before each status transition to DOWNLOADING/NEEDS_REVIEW, and `fail_step` in the except block.

Now the downloader — this one also has the skip_step for resizing:

Now the resizer — it has multiple failure paths:

Now for the ffmpeg not found and ffmpeg failure paths in resizer:

Now transcriber, summarizer, extractor, resolver — these all follow the same simple pattern:

Summarizer:

Extractor:

Resolver:

**Step 6: Modify `admin.py`**

Now add the ProcessingRunInlineForEpisode to EpisodeAdmin:

Now update the `reprocess` action to create a run:

Now add the ProcessingRunAdmin with ProcessingStepInline at the end of the file:

**Step 7: Apply migration and run tests**

All 81 tests pass. Now let me also run `check`:

Everything passes. Here's a summary of all changes:

**New files:**
- `episodes/processing.py` — Helper functions (`create_run`, `get_active_run`, `start_step`, `complete_step`, `fail_step`, `skip_step`) for recording processing progress. All are no-ops if no active run exists.
- `episodes/migrations/0008_processingrun_processingstep.py` — Migration for the new models.

**Modified files:**
- `episodes/models.py` — Added `PIPELINE_STEPS` constant, `ProcessingRun` model (tracks per-attempt status), and `ProcessingStep` model (tracks per-step status within a run).
- `episodes/signals.py` — Calls `create_run(instance)` when a new PENDING episode is created.
- `episodes/scraper.py` — Added `start_step`/`complete_step`/`fail_step` calls.
- `episodes/downloader.py` — Added `start_step`/`complete_step`/`fail_step` calls, plus `skip_step` for RESIZING when file is small enough.
- `episodes/resizer.py` — Added `start_step`/`complete_step`/`fail_step` calls (including all early-return failure paths).
- `episodes/transcriber.py` — Added `start_step`/`complete_step`/`fail_step` calls.
- `episodes/summarizer.py` — Added `start_step`/`complete_step`/`fail_step` calls.
- `episodes/extractor.py` — Added `start_step`/`complete_step`/`fail_step` calls.
- `episodes/resolver.py` — Added `start_step`/`complete_step`/`fail_step` calls.
- `episodes/admin.py` — Added `ProcessingRunAdmin` with `ProcessingStepInline`, `ProcessingRunInlineForEpisode` on `EpisodeAdmin`, `retry_from_failure` action, and updated `reprocess` to create a run.

### User

The current Django admin UI for Episodes offers these three actions:
How could we introduce the posibility to the user to trigger re-processing from a given step without making a huge action list?

### Assistant

Good question. A few options:

**Intermediate page (best fit for Django admin)** — Replace "Reprocess" and "Retry from last failure" with a single "Reprocess..." action. When triggered, it redirects to an intermediate confirmation page with a dropdown to pick the starting step (pre-selected to "scraping" for full reprocess, or to the failed step if the episode is failed). This is a standard Django admin pattern — no extra JS, no action bloat.

**On the detail page** — Add a "Reprocess from step" dropdown + button directly on the Episode change form (as a custom template or fieldset). More discoverable for single-episode operations, but requires a custom template override.

**My recommendation:** the intermediate page approach. It keeps the action list short (just "Reprocess..." instead of two actions), works for bulk operations, and is the idiomatic Django admin way to collect user input before executing an action.

Want me to implement it?

### User

Two questions: 1) in the Intermediate page, how are we going to show the user the last failed step and 2) will this approach also work when we want to trigger batch re-processing?

### Assistant

1. **Last failed step**: On the intermediate page, we show a table listing each selected episode with its title, current status, and last failed step (pulled from the most recent failed `ProcessingRun`). The dropdown defaults to the failed step when there's one failed episode, or to "scraping" (full reprocess) when selecting multiple with different failure points. The user can always override.

2. **Batch reprocessing**: Yes — Django admin actions inherently work on querysets. The intermediate page would show all selected episodes in the table, and the user picks a single starting step that applies to all of them. This covers both cases:
   - Select 5 episodes that all failed at "extracting" → pick "extracting" → all retry from there
   - Select 10 episodes regardless of status → pick "scraping" → full reprocess for all

This replaces both "Reprocess" and "Retry from last failure" with one action: **"Reprocess..."**

Want me to implement it?

### User

yes, please

### Assistant

Now let me check where templates live and the signals file to understand the task dispatch mapping.

Now I'll create the intermediate template and update the admin. The template needs to go in `episodes/templates/admin/episodes/episode/`.

Now update the admin to replace both actions with a single `reprocess` action that shows the intermediate page:

Now replace both action methods with the single intermediate-page action:

Now let me check if the signals will handle dispatching when we set the status. Looking at the signal — it only dispatches for non-created saves with `status` in `update_fields`. But for SCRAPING, the signal doesn't dispatch — the old `reprocess` action called `async_task` directly. Let me check the signal more carefully.

The signal dispatches for DOWNLOADING, RESIZING, TRANSCRIBING, SUMMARIZING, EXTRACTING, RESOLVING — but NOT for SCRAPING (that's only dispatched on create). So I need to handle SCRAPING explicitly in the reprocess action, like the old code did.

Now let's run the tests to make sure everything still passes:

One test failure — the reprocess admin test expects the old direct-action behavior. Let me read it:

The test now needs to be a two-step flow: first POST triggers the intermediate page, then a second POST with `from_step` executes. Let me update the test:

All 82 tests pass. Here's what changed:

**Replaced two actions with one: "Reprocess selected episodes..."**

When triggered, it shows an intermediate page with:
- A table of selected episodes showing title, current status, and last failed step (from the most recent failed `ProcessingRun`)
- A dropdown to pick the starting step, defaulting to the common failed step if all selected episodes failed at the same step, or "Scraping" otherwise
- Works for batch operations — pick one step that applies to all selected episodes

**Files changed:**
- `episodes/admin.py` — Merged `reprocess` + `retry_from_failure` into a single `reprocess` action with intermediate page flow (`_show_reprocess_page` / `_execute_reprocess`)
- `episodes/templates/admin/episodes/episode/reprocess.html` — New template for the intermediate confirmation page
- `episodes/tests/test_admin.py` — Updated test to cover both the intermediate page display and the execution step

### User

Why do we need to handle SCRAPING explicitly in the reprocess action, can we refactor the implementation so that all signals are handled in the same way?

### Assistant

Good point. The asymmetry exists because the signal only dispatches SCRAPING on `created=True`, not on status updates. If we add SCRAPING to the status-change dispatch in the signal, everything becomes uniform and the admin doesn't need to special-case it.

I'll add SCRAPING to the status-change dispatch, then remove the special case from admin.

Now remove the special case from admin:

Now update the test — it was patching `episodes.admin.async_task` which no longer exists there. The dispatch now goes through the signal:

All 82 tests pass. The change was straightforward:

- **`signals.py`**: Added `SCRAPING` to the status-change dispatch block, so it's handled the same way as every other step.
- **`admin.py`**: Removed the `async_task` import and the `if from_step == SCRAPING` special case — the signal now handles it uniformly via `episode.save(update_fields=["status", ...])`.
- **`test_admin.py`**: Updated to assert against `episodes.signals.async_task` instead of the now-removed `episodes.admin.async_task`.

### User

I've restarted "uv run python manage.py runserver" and "uv run python manage.py qcluster" and tested re-processing but I do not see any "Processing runs" created. Do I need to apply a migration?

### Assistant

Migration is applied. The issue is that the reprocess action sets the status to SCRAPING, which triggers the signal — but the signal's status-change dispatch only fires for **non-created** saves where `update_fields` contains `"status"`. Let me trace the flow more carefully.

The `_execute_reprocess` code looks correct — it calls `create_run()` then saves with `update_fields=["status", ...]` which should trigger the signal. Let me check whether the issue is that the intermediate form POST doesn't include `_selected_action`, which Django admin actions require to build the queryset.

Looking at the template:

Found it. The form posts back to the changelist URL but is missing the `action` and `_selected_action` hidden fields. Without those, Django admin doesn't route the POST to the `reprocess` action method at all — it just renders the changelist normally. The `_execute_reprocess` method never gets called.

All 82 tests pass. The issue was that the intermediate form was missing the `action` and `_selected_action` hidden fields. Without those, Django admin didn't route the second POST back to the `reprocess` action — it just rendered the changelist, so `_execute_reprocess` (which calls `create_run`) never ran.

### User

It works now! Thanks! In the Processing Runs list page, in the first column we want to change the title to "Episode (Run)" and show the episode title and the run in parenthesis.

### Assistant

Done. The first column now shows "Episode (Run)" as the header, with values like `John Coltrane - Saxophonlegende und spiritueller Sinnsucher (3)`.

### User

Create a PR for this feature.

### Assistant

Now I need to create the documentation files per AGENTS.md requirements before committing. Let me check the doc structure and README.

Let me check the README Features & Fixes section and an example feature doc for format reference.

Now I need to check an example session transcript for the format, then create the plan, feature doc, and session transcript. Let me look at a compact example.

Now let me create all the documentation files. I'll write the plan, feature doc, and session transcript.

Let me write the plan doc (which mirrors the plan from the user's message) and the feature doc while the agent reads the transcript.

Now let me wait for the background agent to finish so I can use the planning session context for the session transcript.

The agent is still running. Let me check if the final summary is available.

The agent is still working. I have enough context from the conversation to write the session transcript — I was part of it. Let me write it now.

Now update the README Features & Fixes table:

Now let me commit and create the PR.

PR created: https://github.com/rafacm/ragtime/pull/32

### User

<task-notification>
<task-id>a74240dde12ec3915</task-id>
<tool-use-id>toolu_016PPNcsE7QwWecmZ2aZhF4T</tool-use-id>
<output-file>/private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/f338e746-754d-4bdf-8623-4e983b96c26e/tasks/a74240dde12ec3915.output</output-file>
<status>completed</status>
<summary>Agent "Read plan transcript for context" completed</summary>
<result>Here is the summary of the planning session:

---

**Session: Processing Status Tracking (ebcf8a85, 2026-03-14, ~13:46-13:57)**

**1. What the user asked for initially:**

The user started by asking "How do we currently track the processing status for an episode?" After seeing the answer (a single `status` CharField with a linear enum), the user said this was too simple. The core problem: when a pipeline step fails, the only option is full reprocessing from scratch, which re-runs expensive LLM calls (summarization, extraction, resolution) that already succeeded, wasting money. The user requested:
- Per-step tracking with start/finish timestamps and success/error status
- Admin UI actions for "retry from last failure" and full reprocessing
- Support for multiple processing runs per episode, with skipped-step tracking
- All of this visible in the Django admin

**2. What the assistant explored/planned:**

- Read the Episode model to understand the current status enum (8 pipeline steps + PENDING/NEEDS_REVIEW/READY/FAILED)
- Launched sub-agents to explore: (a) how pipeline steps are triggered/executed across all step files (scraper, downloader, resizer, transcriber, summarizer, extractor, resolver), signals, and Django Q2 tasks; (b) the current admin configuration and AGENTS.md conventions
- Asked the user a clarifying question: should the plan cover only the 8 existing steps or all 12 from the spec (including not-yet-implemented submit, dedup, chunk)? User chose **existing steps only**.

**3. Key decisions made:**

- **Two new models**: `ProcessingRun` (per processing attempt, with status/timestamps/resume-from-step) and `ProcessingStep` (per step within a run, with status/timestamps/error)
- **New helper module** `episodes/processing.py` with functions: `create_run`, `get_active_run`, `start_step`, `complete_step`, `fail_step`, `skip_step` -- all designed as no-ops if no active run exists (graceful degradation)
- **Keep the existing Episode.status field** as-is for quick-glance current state; the new models provide the detailed history
- **Instrument all 7 step files** with start/complete/fail calls (same pattern); special case for downloader skipping the resize step
- **Admin changes**: new `ProcessingRunAdmin` with step inline, `ProcessingRunInlineForEpisode` on EpisodeAdmin, a new `retry_from_failure` action, and modify the existing `reprocess` action to create a run
- **Scope**: existing 8 steps only; new steps get added when implemented
- **12 files touched** total (7 step files, models, processing helper [new], signals, admin, migration)

The plan was saved to `/Users/rafa/.claude/plans/humble-dazzling-pearl.md` and the session exited plan mode, ready for implementation.</result>
<usage><total_tokens>37114</total_tokens><tool_uses>13</tool_uses><duration_ms>79908</duration_ms></usage>
</task-notification>
Full transcript available at: /private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/f338e746-754d-4bdf-8623-4e983b96c26e/tasks/a74240dde12ec3915.output

### Assistant

The background agent finished — its findings align with the session transcript I already wrote. The PR is ready: https://github.com/rafacm/ragtime/pull/32

### User

I tested with a new episode and it seems that the processing goes in a loop. Here are the logs from the Danjo Q task execution:
 ragtime  uv run python manage.py qcluster
14:27:40 [Q] INFO Q Cluster thirteen-victor-alabama-steak starting.
14:27:40 [Q] INFO Process-cc7cb98877ef44d790db581ac79a1ae7 guarding cluster thirteen-victor-alabama-steak [ragtime]
14:27:40 [Q] INFO Q Cluster thirteen-victor-alabama-steak [ragtime] running.
14:27:40 [Q] INFO Process-82863c3a7c394112b36028809d832c15 monitoring at 11601
14:27:40 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d ready for work at 11600
14:27:40 [Q] INFO Process-525a3c0917d1448a8f595901d9417626 pushing tasks at 11602
14:27:40 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 ready for work at 11599
14:35:24 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing ack-moon-potato-pip 'episodes.scraper.scrape_episode'
14:35:24 [Q] INFO Enqueued [ragtime] 30
14:35:25 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing august-music-football-zebra 'episodes.scraper.scrape_episode'
14:35:25 [Q] INFO Enqueued [ragtime] 31
14:35:28 [Q] INFO Enqueued [ragtime] 32
14:35:28 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing wolfram-minnesota-tennis-mike 'episodes.scraper.scrape_episode'
14:35:28 [Q] INFO Enqueued [ragtime] 33
14:35:28 [Q] INFO Enqueued [ragtime] 34
14:35:28 [Q] INFO Processed 'episodes.scraper.scrape_episode' (ack-moon-potato-pip)
14:35:28 [Q] INFO Processed 'episodes.scraper.scrape_episode' (wolfram-minnesota-tennis-mike)
14:35:28 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing zebra-speaker-spaghetti-bluebird 'episodes.downloader.download_episode'
14:35:29 [Q] INFO Enqueued [ragtime] 35
14:35:29 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing orange-alabama-idaho-red 'episodes.scraper.scrape_episode'
14:35:29 [Q] INFO Enqueued [ragtime] 36
14:35:29 [Q] INFO Enqueued [ragtime] 37
14:35:29 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing three-vegan-dakota-alanine 'episodes.downloader.download_episode'
14:35:29 [Q] INFO Processed 'episodes.scraper.scrape_episode' (august-music-football-zebra)
14:35:29 [Q] INFO Processed 'episodes.scraper.scrape_episode' (orange-alabama-idaho-red)
14:35:29 [Q] INFO Enqueued [ragtime] 38
14:35:29 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing comet-fanta-delaware-whiskey 'episodes.downloader.download_episode'
Episode 5 has status 'transcribing', expected 'downloading'
14:35:29 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing louisiana-sixteen-september-speaker 'episodes.scraper.scrape_episode'
14:35:29 [Q] INFO Processed 'episodes.downloader.download_episode' (three-vegan-dakota-alanine)
14:35:29 [Q] INFO Enqueued [ragtime] 39
14:35:29 [Q] INFO Processed 'episodes.downloader.download_episode' (comet-fanta-delaware-whiskey)
14:35:29 [Q] INFO Enqueued [ragtime] 40
14:35:29 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing pip-cold-sierra-single 'episodes.downloader.download_episode'
14:35:29 [Q] INFO Processed 'episodes.scraper.scrape_episode' (louisiana-sixteen-september-speaker)
14:35:29 [Q] INFO Enqueued [ragtime] 41
14:35:29 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing seven-failed-minnesota-summer 'episodes.transcriber.transcribe_episode'
14:35:29 [Q] INFO Processed 'episodes.downloader.download_episode' (zebra-speaker-spaghetti-bluebird)
14:35:30 [Q] INFO Enqueued [ragtime] 42
14:35:30 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing aspen-william-green-triple 'episodes.scraper.scrape_episode'
14:35:30 [Q] INFO Enqueued [ragtime] 43
14:35:30 [Q] INFO Enqueued [ragtime] 44
14:35:30 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing maine-twenty-massachusetts-seventeen 'episodes.downloader.download_episode'
14:35:30 [Q] INFO Processed 'episodes.downloader.download_episode' (pip-cold-sierra-single)
14:35:30 [Q] INFO Processed 'episodes.scraper.scrape_episode' (aspen-william-green-triple)
14:35:31 [Q] INFO Enqueued [ragtime] 45
14:35:31 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing xray-music-may-shade 'episodes.transcriber.transcribe_episode'
14:35:31 [Q] INFO Processed 'episodes.downloader.download_episode' (maine-twenty-massachusetts-seventeen)
14:35:49 [Q] INFO Enqueued [ragtime] 46
14:35:49 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing ink-shade-louisiana-earth 'episodes.transcriber.transcribe_episode'
Episode 5 has status 'summarizing', expected 'transcribing'
14:35:49 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing seventeen-connecticut-fix-fish 'episodes.scraper.scrape_episode'
14:35:49 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (seven-failed-minnesota-summer)
14:35:49 [Q] INFO Enqueued [ragtime] 47
14:35:49 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (ink-shade-louisiana-earth)
14:35:49 [Q] INFO Enqueued [ragtime] 48
14:35:49 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing zebra-alpha-sad-violet 'episodes.downloader.download_episode'
14:35:49 [Q] INFO Processed 'episodes.scraper.scrape_episode' (seventeen-connecticut-fix-fish)
14:35:49 [Q] INFO Enqueued [ragtime] 49
14:35:49 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing tango-diet-comet-hydrogen 'episodes.transcriber.transcribe_episode'
14:35:49 [Q] INFO Processed 'episodes.downloader.download_episode' (zebra-alpha-sad-violet)
14:35:55 [Q] INFO Enqueued [ragtime] 50
14:35:55 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing fish-oxygen-ten-cold 'episodes.summarizer.summarize_episode'
14:35:55 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (xray-music-may-shade)
14:36:06 [Q] INFO Enqueued [ragtime] 51
14:36:06 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing dakota-july-speaker-india 'episodes.scraper.scrape_episode'
14:36:06 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (fish-oxygen-ten-cold)
14:36:06 [Q] INFO Enqueued [ragtime] 52
14:36:06 [Q] INFO Enqueued [ragtime] 53
14:36:06 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing zebra-december-arizona-fifteen 'episodes.downloader.download_episode'
14:36:06 [Q] INFO Processed 'episodes.scraper.scrape_episode' (dakota-july-speaker-india)
14:36:07 [Q] INFO Enqueued [ragtime] 54
14:36:07 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing ohio-florida-don-fanta 'episodes.transcriber.transcribe_episode'
14:36:07 [Q] INFO Processed 'episodes.downloader.download_episode' (zebra-december-arizona-fifteen)
14:36:16 [Q] INFO Enqueued [ragtime] 55
14:36:16 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing west-bacon-wyoming-nebraska 'episodes.summarizer.summarize_episode'
14:36:16 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (tango-diet-comet-hydrogen)
14:36:24 [Q] INFO Enqueued [ragtime] 56
14:36:24 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing romeo-blue-crazy-freddie 'episodes.extractor.extract_entities'
14:36:24 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (west-bacon-wyoming-nebraska)
14:36:25 [Q] INFO Enqueued [ragtime] 57
14:36:25 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing black-artist-hotel-snake 'episodes.scraper.scrape_episode'
14:36:25 [Q] INFO Enqueued [ragtime] 58
14:36:25 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (ohio-florida-don-fanta)
14:36:25 [Q] INFO Enqueued [ragtime] 59
14:36:25 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing hawaii-beer-arkansas-tennis 'episodes.downloader.download_episode'
14:36:25 [Q] INFO Processed 'episodes.scraper.scrape_episode' (black-artist-hotel-snake)
14:36:25 [Q] INFO Enqueued [ragtime] 60
14:36:25 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing gee-maryland-beryllium-moon 'episodes.transcriber.transcribe_episode'
14:36:25 [Q] INFO Processed 'episodes.downloader.download_episode' (hawaii-beer-arkansas-tennis)
14:36:42 [Q] INFO Enqueued [ragtime] 61
14:36:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing robin-queen-nebraska-edward 'episodes.summarizer.summarize_episode'
Episode 5 has status 'resolving', expected 'summarizing'
14:36:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing may-connecticut-stream-washington 'episodes.extractor.extract_entities'
Episode 5 has status 'resolving', expected 'extracting'
14:36:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing alpha-aspen-two-emma 'episodes.summarizer.summarize_episode'
14:36:42 [Q] INFO Processed 'episodes.extractor.extract_entities' (romeo-blue-crazy-freddie)
Episode 5 has status 'resolving', expected 'summarizing'
14:36:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing sad-october-johnny-neptune 'episodes.scraper.scrape_episode'
14:36:42 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (robin-queen-nebraska-edward)
14:36:42 [Q] INFO Enqueued [ragtime] 62
14:36:42 [Q] INFO Enqueued [ragtime] 63
14:36:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing connecticut-november-early-jig 'episodes.downloader.download_episode'
14:36:42 [Q] INFO Processed 'episodes.extractor.extract_entities' (may-connecticut-stream-washington)
14:36:42 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (alpha-aspen-two-emma)
14:36:42 [Q] INFO Processed 'episodes.scraper.scrape_episode' (sad-october-johnny-neptune)
14:36:43 [Q] INFO Enqueued [ragtime] 64
14:36:43 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing fruit-sierra-hawaii-three 'episodes.transcriber.transcribe_episode'
14:36:43 [Q] INFO Processed 'episodes.downloader.download_episode' (connecticut-november-early-jig)
14:36:43 [Q] INFO Enqueued [ragtime] 65
14:36:43 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing sad-victor-tennis-carpet 'episodes.resolver.resolve_entities'
Episode 5 has status 'summarizing', expected 'resolving'
14:36:43 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing mountain-seven-finch-blossom 'episodes.scraper.scrape_episode'
14:36:43 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (gee-maryland-beryllium-moon)
14:36:43 [Q] INFO Processed 'episodes.resolver.resolve_entities' (sad-victor-tennis-carpet)
14:36:43 [Q] INFO Enqueued [ragtime] 66
14:36:43 [Q] INFO Enqueued [ragtime] 67
14:36:43 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing ack-nebraska-arizona-cup 'episodes.downloader.download_episode'
14:36:43 [Q] INFO Processed 'episodes.scraper.scrape_episode' (mountain-seven-finch-blossom)
14:36:44 [Q] INFO Enqueued [ragtime] 68
14:36:44 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing pizza-virginia-blossom-zulu 'episodes.transcriber.transcribe_episode'
14:36:44 [Q] INFO Processed 'episodes.downloader.download_episode' (ack-nebraska-arizona-cup)
14:37:01 [Q] INFO Enqueued [ragtime] 69
14:37:01 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing october-one-fish-seventeen 'episodes.summarizer.summarize_episode'
14:37:01 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (fruit-sierra-hawaii-three)
14:37:04 [Q] INFO Enqueued [ragtime] 70
14:37:04 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing wisconsin-april-mississippi-michigan 'episodes.scraper.scrape_episode'
14:37:04 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (pizza-virginia-blossom-zulu)
14:37:04 [Q] INFO Enqueued [ragtime] 71
14:37:04 [Q] INFO Enqueued [ragtime] 72
14:37:04 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing fruit-march-emma-foxtrot 'episodes.downloader.download_episode'
14:37:04 [Q] INFO Processed 'episodes.scraper.scrape_episode' (wisconsin-april-mississippi-michigan)
14:37:05 [Q] INFO Enqueued [ragtime] 73
14:37:05 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing carpet-saturn-robert-speaker 'episodes.transcriber.transcribe_episode'
14:37:05 [Q] INFO Processed 'episodes.downloader.download_episode' (fruit-march-emma-foxtrot)
14:37:08 [Q] INFO Enqueued [ragtime] 74
14:37:08 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing kitten-xray-illinois-two 'episodes.summarizer.summarize_episode'
Episode 5 has status 'extracting', expected 'summarizing'
14:37:08 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing juliet-carolina-failed-mars 'episodes.summarizer.summarize_episode'
14:37:08 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (october-one-fish-seventeen)
Episode 5 has status 'extracting', expected 'summarizing'
14:37:08 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing nine-kentucky-mango-romeo 'episodes.scraper.scrape_episode'
14:37:08 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (kitten-xray-illinois-two)
14:37:08 [Q] INFO Enqueued [ragtime] 75
14:37:08 [Q] INFO Enqueued [ragtime] 76
14:37:08 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing helium-november-berlin-comet 'episodes.downloader.download_episode'
14:37:08 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (juliet-carolina-failed-mars)
14:37:08 [Q] INFO Processed 'episodes.scraper.scrape_episode' (nine-kentucky-mango-romeo)
14:37:09 [Q] INFO Enqueued [ragtime] 77
14:37:09 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing friend-burger-alabama-november 'episodes.transcriber.transcribe_episode'
14:37:09 [Q] INFO Processed 'episodes.downloader.download_episode' (helium-november-berlin-comet)
14:37:28 [Q] INFO Enqueued [ragtime] 78
14:37:28 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing apart-salami-sink-wisconsin 'episodes.extractor.extract_entities'
14:37:28 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (carpet-saturn-robert-speaker)
Episode 5 has status 'summarizing', expected 'extracting'
14:37:28 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing tango-robin-washington-river 'episodes.scraper.scrape_episode'
14:37:28 [Q] INFO Processed 'episodes.extractor.extract_entities' (apart-salami-sink-wisconsin)
14:37:28 [Q] INFO Enqueued [ragtime] 79
14:37:28 [Q] INFO Enqueued [ragtime] 80
14:37:28 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing berlin-march-apart-alabama 'episodes.downloader.download_episode'
14:37:28 [Q] INFO Processed 'episodes.scraper.scrape_episode' (tango-robin-washington-river)
14:37:28 [Q] INFO Enqueued [ragtime] 81
14:37:28 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing arizona-two-hotel-music 'episodes.transcriber.transcribe_episode'
14:37:28 [Q] INFO Processed 'episodes.downloader.download_episode' (berlin-march-apart-alabama)
14:37:33 [Q] INFO Enqueued [ragtime] 82
14:37:33 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing florida-robin-low-william 'episodes.summarizer.summarize_episode'
14:37:33 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (friend-burger-alabama-november)
14:37:40 [Q] INFO Enqueued [ragtime] 83
14:37:40 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing fanta-artist-lamp-twenty 'episodes.scraper.scrape_episode'
14:37:40 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (florida-robin-low-william)
14:37:40 [Q] INFO Enqueued [ragtime] 84
14:37:40 [Q] INFO Enqueued [ragtime] 85
14:37:40 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing carolina-single-mississippi-queen 'episodes.downloader.download_episode'
14:37:40 [Q] INFO Processed 'episodes.scraper.scrape_episode' (fanta-artist-lamp-twenty)
14:37:40 [Q] INFO Enqueued [ragtime] 86
14:37:40 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing bacon-bluebird-florida-orange 'episodes.transcriber.transcribe_episode'
14:37:40 [Q] INFO Processed 'episodes.downloader.download_episode' (carolina-single-mississippi-queen)
14:37:52 [Q] INFO Enqueued [ragtime] 87
14:37:52 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing berlin-muppet-burger-blossom 'episodes.summarizer.summarize_episode'
14:37:52 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (arizona-two-hotel-music)
14:37:59 [Q] INFO Enqueued [ragtime] 88
14:37:59 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing black-louisiana-victor-diet 'episodes.extractor.extract_entities'
14:37:59 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (berlin-muppet-burger-blossom)
14:38:00 [Q] INFO Enqueued [ragtime] 89
14:38:00 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing quiet-kitten-spring-minnesota 'episodes.scraper.scrape_episode'
14:38:00 [Q] INFO Enqueued [ragtime] 90
14:38:00 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (bacon-bluebird-florida-orange)
14:38:00 [Q] INFO Enqueued [ragtime] 91
14:38:00 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing maine-comet-oregon-single 'episodes.downloader.download_episode'
14:38:00 [Q] INFO Processed 'episodes.scraper.scrape_episode' (quiet-kitten-spring-minnesota)
14:38:00 [Q] INFO Enqueued [ragtime] 92
14:38:00 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing yankee-robin-texas-leopard 'episodes.transcriber.transcribe_episode'
14:38:00 [Q] INFO Processed 'episodes.downloader.download_episode' (maine-comet-oregon-single)
14:38:12 [Q] INFO Enqueued [ragtime] 93
14:38:12 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing quebec-sixteen-one-illinois 'episodes.summarizer.summarize_episode'
Episode 5 has status 'resolving', expected 'summarizing'
14:38:12 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing mirror-single-yellow-pizza 'episodes.extractor.extract_entities'
14:38:12 [Q] INFO Processed 'episodes.extractor.extract_entities' (black-louisiana-victor-diet)
Episode 5 has status 'resolving', expected 'extracting'
14:38:12 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing ohio-queen-hamper-fanta 'episodes.summarizer.summarize_episode'
14:38:12 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (quebec-sixteen-one-illinois)
Episode 5 has status 'resolving', expected 'summarizing'
14:38:12 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing london-five-island-maryland 'episodes.scraper.scrape_episode'
14:38:12 [Q] INFO Processed 'episodes.extractor.extract_entities' (mirror-single-yellow-pizza)
14:38:12 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (ohio-queen-hamper-fanta)
14:38:12 [Q] INFO Enqueued [ragtime] 94
14:38:12 [Q] INFO Enqueued [ragtime] 95
14:38:12 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing coffee-quiet-pasta-leopard 'episodes.downloader.download_episode'
14:38:12 [Q] INFO Processed 'episodes.scraper.scrape_episode' (london-five-island-maryland)
14:38:13 [Q] INFO Enqueued [ragtime] 96
14:38:13 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing crazy-magazine-wisconsin-muppet 'episodes.transcriber.transcribe_episode'
14:38:13 [Q] INFO Processed 'episodes.downloader.download_episode' (coffee-quiet-pasta-leopard)
14:38:19 [Q] INFO Enqueued [ragtime] 97
14:38:19 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing earth-massachusetts-burger-uranus 'episodes.resolver.resolve_entities'
Episode 5 has status 'summarizing', expected 'resolving'
14:38:19 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing december-video-nine-minnesota 'episodes.scraper.scrape_episode'
14:38:19 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (yankee-robin-texas-leopard)
14:38:19 [Q] INFO Enqueued [ragtime] 98
14:38:19 [Q] INFO Processed 'episodes.resolver.resolve_entities' (earth-massachusetts-burger-uranus)
14:38:19 [Q] INFO Enqueued [ragtime] 99
14:38:19 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing magnesium-two-oranges-ceiling 'episodes.downloader.download_episode'
14:38:19 [Q] INFO Processed 'episodes.scraper.scrape_episode' (december-video-nine-minnesota)
14:38:19 [Q] INFO Enqueued [ragtime] 100
14:38:19 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing monkey-comet-purple-dakota 'episodes.transcriber.transcribe_episode'
14:38:19 [Q] INFO Processed 'episodes.downloader.download_episode' (magnesium-two-oranges-ceiling)
14:38:40 [Q] INFO Enqueued [ragtime] 101
14:38:40 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing whiskey-montana-oscar-alanine 'episodes.summarizer.summarize_episode'
14:38:40 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (crazy-magazine-wisconsin-muppet)
14:38:42 [Q] INFO Enqueued [ragtime] 102
14:38:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing magnesium-timing-triple-failed 'episodes.scraper.scrape_episode'
14:38:42 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (monkey-comet-purple-dakota)
14:38:42 [Q] INFO Enqueued [ragtime] 103
14:38:42 [Q] INFO Enqueued [ragtime] 104
14:38:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing oklahoma-sweet-michigan-golf 'episodes.downloader.download_episode'
14:38:42 [Q] INFO Processed 'episodes.scraper.scrape_episode' (magnesium-timing-triple-failed)
14:38:42 [Q] INFO Enqueued [ragtime] 105
14:38:42 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing yankee-mockingbird-wyoming-virginia 'episodes.transcriber.transcribe_episode'
14:38:42 [Q] INFO Processed 'episodes.downloader.download_episode' (oklahoma-sweet-michigan-golf)
14:38:49 [Q] INFO Enqueued [ragtime] 106
14:38:49 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing avocado-lake-twenty-equal 'episodes.summarizer.summarize_episode'
Episode 5 has status 'extracting', expected 'summarizing'
14:38:49 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing magazine-robert-carbon-fifteen 'episodes.summarizer.summarize_episode'
14:38:49 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (whiskey-montana-oscar-alanine)
Episode 5 has status 'extracting', expected 'summarizing'
14:38:49 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing finch-failed-october-louisiana 'episodes.scraper.scrape_episode'
14:38:49 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (avocado-lake-twenty-equal)
14:38:49 [Q] INFO Enqueued [ragtime] 107
14:38:49 [Q] INFO Enqueued [ragtime] 108
14:38:49 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing leopard-stream-pizza-cat 'episodes.downloader.download_episode'
14:38:49 [Q] INFO Processed 'episodes.summarizer.summarize_episode' (magazine-robert-carbon-fifteen)
14:38:49 [Q] INFO Processed 'episodes.scraper.scrape_episode' (finch-failed-october-louisiana)
14:38:50 [Q] INFO Enqueued [ragtime] 109
14:38:50 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 processing beryllium-blossom-zebra-enemy 'episodes.transcriber.transcribe_episode'
14:38:50 [Q] INFO Processed 'episodes.downloader.download_episode' (leopard-stream-pizza-cat)
^C14:38:59 [Q] INFO Q Cluster thirteen-victor-alabama-steak stopping.
14:39:00 [Q] INFO Process-cc7cb98877ef44d790db581ac79a1ae7 stopping cluster processes
14:39:00 [Q] INFO Process-525a3c0917d1448a8f595901d9417626 stopped pushing tasks
14:39:05 [Q] INFO Enqueued [ragtime] 110
14:39:05 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing uncle-maine-two-mango 'episodes.extractor.extract_entities'
Episode 5 has status 'summarizing', expected 'extracting'
14:39:05 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing indigo-mockingbird-pluto-william 'episodes.scraper.scrape_episode'
14:39:05 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (yankee-mockingbird-wyoming-virginia)
14:39:05 [Q] INFO Processed 'episodes.extractor.extract_entities' (uncle-maine-two-mango)
14:39:05 [Q] INFO Enqueued [ragtime] 111
14:39:05 [Q] INFO Enqueued [ragtime] 112
14:39:05 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing virginia-massachusetts-beryllium-triple 'episodes.downloader.download_episode'
14:39:05 [Q] INFO Processed 'episodes.scraper.scrape_episode' (indigo-mockingbird-pluto-william)
14:39:05 [Q] INFO Enqueued [ragtime] 113
14:39:05 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d processing california-hotel-rugby-nineteen 'episodes.transcriber.transcribe_episode'
14:39:05 [Q] INFO Processed 'episodes.downloader.download_episode' (virginia-massachusetts-beryllium-triple)
14:39:10 [Q] INFO Enqueued [ragtime] 114
14:39:10 [Q] INFO Process-49a8e1f3e4df40c398d8dd50074505a0 stopped doing work
14:39:10 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (beryllium-blossom-zebra-enemy)
14:39:25 [Q] INFO Enqueued [ragtime] 115
14:39:25 [Q] INFO Process-06c45f6f7b5e4a28a03934fbf7f9510d stopped doing work
14:39:25 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (california-hotel-rugby-nineteen)
14:39:25 [Q] INFO Process-cc7cb98877ef44d790db581ac79a1ae7 waiting for the monitor.
14:39:25 [Q] INFO Process-82863c3a7c394112b36028809d832c15 stopped monitoring results
14:39:25 [Q] INFO Q Cluster thirteen-victor-alabama-steak has stopped.

### Assistant

I see the problem. Adding SCRAPING to the signal dispatch created an infinite loop. Here's why:

1. Admin sets `status = SCRAPING`, saves → signal fires → queues `scrape_episode`
2. `scrape_episode` sets `status = SCRAPING` again (line 100-101 of scraper.py), saves → signal fires → queues another `scrape_episode`
3. Repeat forever

The scraper is unique — it's the only step function that sets its **own** status at the start. All other steps rely on the **previous** step setting their status. That's why SCRAPING can't be in the signal dispatch.

Now add the explicit `async_task` call back in admin for the SCRAPING case:

Now update the test back:

All 82 tests pass. The fix: removed SCRAPING from the signal dispatch and added the explicit `async_task` call back in the admin action with a comment explaining why.

The scraper is the only step function that sets its own status (`status = SCRAPING`) at the start — all other steps rely on the previous step setting their status. So dispatching SCRAPING via the signal creates a loop: admin sets SCRAPING → signal queues scraper → scraper sets SCRAPING again → signal queues another scraper → infinite loop.

Let me amend the commit on the PR.

Pushed the fix to the PR. You should be able to restart `qcluster` and test again — the loop is gone.

### User

Does deleting an Episode also delete its processing runs?

### Assistant

Yes. `ProcessingRun` has `on_delete=models.CASCADE` on its `episode` FK, and `ProcessingStep` has `on_delete=models.CASCADE` on its `run` FK. Deleting an episode cascades through both.

### User

When adding an Episode, I can see in the Django admin UI the "Entity Mentions" and the "Processing Runs" sections. They should not be visible there.

### Assistant

The inlines show on all pages including add. I need to hide them when creating a new episode.

Now add a `get_inlines` method that only returns inlines when editing an existing episode:

All tests pass. The inlines now only appear when editing an existing episode, not on the add form.

Fixed and pushed. The add form now shows only the URL field — no empty inlines.

### User

In the Episode detail page in the Django admin UI, at the bottom there is a "Processing Runs" section. We want to add a column called "Run number" with a link to the Processing Run detail page for that run.

### Assistant

We already have `show_change_link=True` which adds a link, but the user wants an explicit "Run number" column. Let me replace `show_change_link` with a custom column that links to the ProcessingRun detail page.

Done. The Processing Runs inline on the Episode detail page now has a "Run number" column with the run's ID as a clickable link to its detail page.

### User

Change the column name to "Run ID" since what we are displaying there is actually the ID. Remove also the text added in each line, like this one "Run 3 for Der Jazzpianist David Gazarov (running)"

### Assistant

The "Run 3 for ..." text comes from `ProcessingRun.__str__`. That's what Django displays in the inline's first column by default, but since we're using `fields` to control which columns show, it appears as the `__str__` representation. Let me check — actually that text shows in the inline row header. Let me look at the model:

The `__str__` is what shows in the inline row. The inline uses `TabularInline` which shows `__str__` in each row's header cell. Since we now have a dedicated "Run ID" column, I'll simplify `__str__`:

Also update the `episode_run` display on the ProcessingRun list page since `__str__` changed:

That's fine — `episode_run` constructs its own string from `obj.episode` and `obj.pk`, not from `ProcessingRun.__str__`.

Done. Column is now "Run ID" and the inline rows just show "Run 3" instead of the verbose text.

### User

That line is still shown. See attached screenshow. Can we remove it alltogether?

### Assistant

That "Run 4" / "Run 3" text is the `__str__` shown in the inline row header — Django's `TabularInline` always displays it. The simplest way to hide it is to return an empty string:

But that would also affect the ProcessingRun list page's `episode_run` column and anywhere else `__str__` is used. Better to keep a useful `__str__` and hide the header via CSS on the inline instead.

Let me revert that and use a different approach — the inline's `verbose_name` controls the row label prefix:

Actually, the cleanest approach: Django `TabularInline` shows `__str__` in a header cell (`<h2>`) for each row. We can hide it with the inline's `classes` and a small CSS override, or we can simply override the `__str__` to return empty when rendered in the inline context. But the most pragmatic approach is to just return an empty string from `__str__` and update the `episode_run` display to not depend on it:

`episode_run` already constructs its own string — it doesn't use `__str__`. Safe to make `__str__` empty.

Done. The "Run 4" / "Run 3" row headers will no longer appear — the Run ID column with the clickable link is the only identifier now.

### User

Ummm... hiding it via CSS seems a hack to me. Let's then remove the first column and add back the "Run ..." text line. But in the line let's only add the ID.

### Assistant

Done. Each row now shows just the ID (e.g. "4") in the row header, with Django's built-in change link arrow to navigate to the run detail page. No extra column.

### User

Update the PR with the changes.

### Assistant

The PR is already updated — every commit has been pushed to the `feature/processing-status-tracking` branch, so PR #32 already includes all the changes.

https://github.com/rafacm/ragtime/pull/32

### User

When reprocessing several Episodes in batch I see this error in the logs:
14:57:16 [Q] INFO Process-29f70ac19f054583add7790bc22d7e5d processing utah-hot-whiskey-massachusetts 'episodes.resolver.resolve_entities'
Failed to resolve entities for episode 4
Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
sqlite3.OperationalError: database is locked

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/episodes/resolver.py", line 94, in resolve_entities
    EntityMention.objects.filter(episode=episode).delete()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1201, in delete
    num_deleted, num_deleted_per_model = collector.delete()
                                         ~~~~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/deletion.py", line 467, in delete
    count = qs._raw_delete(using=self.using)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1223, in _raw_delete
    return query.get_compiler(using).execute_sql(ROW_COUNT)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 1623, in execute_sql
    cursor.execute(sql, params)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 122, in execute
    return super().execute(sql, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 79, in execute
    return self._execute_with_wrappers(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sql, params, many=False, executor=self._execute
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 92, in _execute_with_wrappers
    return executor(sql, params, many, context)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 100, in _execute
    with self.db.wrap_database_errors:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/utils.py", line 91, in __exit__
    raise dj_exc_value.with_traceback(traceback) from exc_value
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
django.db.utils.OperationalError: database is locked
14:57:27 [Q] INFO Process-29f70ac19f054583add7790bc22d7e5d processing carbon-foxtrot-august-oranges 'episodes.resolver.resolve_entities'
14:57:32 [Q] ERROR Could not save task result
Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/monitor.py", line 123, in save_task
    task_obj = Task.objects.get(id=task["id"], name=task["name"])
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/manager.py", line 87, in manager_method
    return getattr(self.get_queryset(), name)(*args, **kwargs)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 635, in get
    raise self.model.DoesNotExist(
        "%s matching query does not exist." % self.model._meta.object_name
    )
django_q.models.Task.DoesNotExist: Task matching query does not exist.

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
sqlite3.OperationalError: database is locked

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/monitor.py", line 135, in save_task
    task_obj = Task.objects.create(
        id=task["id"],
    ...<11 lines>...
        attempt_count=1,
    )
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/manager.py", line 87, in manager_method
    return getattr(self.get_queryset(), name)(*args, **kwargs)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 665, in create
    obj.save(force_insert=True, using=self.db)
    ~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 902, in save
    self.save_base(
    ~~~~~~~~~~~~~~^
        using=using,
        ^^^^^^^^^^^^
    ...<2 lines>...
        update_fields=update_fields,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 1008, in save_base
    updated = self._save_table(
        raw,
    ...<4 lines>...
        update_fields,
    )
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 1169, in _save_table
    results = self._do_insert(
        cls._base_manager, using, fields, returning_fields, raw
    )
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 1210, in _do_insert
    return manager._insert(
           ~~~~~~~~~~~~~~~^
        [self],
        ^^^^^^^
    ...<3 lines>...
        raw=raw,
        ^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/manager.py", line 87, in manager_method
    return getattr(self.get_queryset(), name)(*args, **kwargs)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1873, in _insert
    return query.get_compiler(using=using).execute_sql(returning_fields)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 1882, in execute_sql
    cursor.execute(sql, params)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 122, in execute
    return super().execute(sql, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 79, in execute
    return self._execute_with_wrappers(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sql, params, many=False, executor=self._execute
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 92, in _execute_with_wrappers
    return executor(sql, params, many, context)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 100, in _execute
    with self.db.wrap_database_errors:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/utils.py", line 91, in __exit__
    raise dj_exc_value.with_traceback(traceback) from exc_value
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
django.db.utils.OperationalError: database is locked
Process Process-c58ef98c116d4b11be77ce323c2683e3:
Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
sqlite3.OperationalError: database is locked

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/multiprocessing/process.py", line 313, in _bootstrap
    self.run()
    ~~~~~~~~^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/multiprocessing/process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/monitor.py", line 53, in monitor
    broker.acknowledge(ack_id)
    ~~~~~~~~~~~~~~~~~~^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/brokers/orm.py", line 93, in acknowledge
    return self.delete(task_id)
           ~~~~~~~~~~~^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/brokers/orm.py", line 90, in delete
    self.get_connection().filter(pk=task_id).delete()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1201, in delete
    num_deleted, num_deleted_per_model = collector.delete()
                                         ~~~~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/deletion.py", line 467, in delete
    count = qs._raw_delete(using=self.using)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1223, in _raw_delete
    return query.get_compiler(using).execute_sql(ROW_COUNT)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 1623, in execute_sql
    cursor.execute(sql, params)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 122, in execute
    return super().execute(sql, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 79, in execute
    return self._execute_with_wrappers(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sql, params, many=False, executor=self._execute
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 92, in _execute_with_wrappers
    return executor(sql, params, many, context)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 100, in _execute
    with self.db.wrap_database_errors:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/utils.py", line 91, in __exit__
    raise dj_exc_value.with_traceback(traceback) from exc_value
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
django.db.utils.OperationalError: database is locked
14:57:37 [Q] CRITICAL reincarnated monitor Process-c58ef98c116d4b11be77ce323c2683e3 after sudden death
14:57:37 [Q] INFO Process-b4c6b5e60734417f8d55f2aa8628466a monitoring at 18313
14:57:41 [Q] ERROR Failed 'episodes.resolver.resolve_entities' (carbon-foxtrot-august-oranges) - database is locked : Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
sqlite3.OperationalError: database is locked

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django_q/worker.py", line 103, in worker
    res = f(*task["args"], **task["kwargs"])
  File "/Users/rafa/Develop/projects/ragtime/episodes/resolver.py", line 80, in resolve_entities
    start_step(episode, Episode.Status.RESOLVING)
    ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/episodes/processing.py", line 48, in start_step
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        status=ProcessingStep.Status.RUNNING,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        started_at=timezone.now(),
        ^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1263, in update
    rows = query.get_compiler(self.db).execute_sql(ROW_COUNT)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 2060, in execute_sql
    row_count = super().execute_sql(result_type)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 1623, in execute_sql
    cursor.execute(sql, params)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 122, in execute
    return super().execute(sql, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 79, in execute
    return self._execute_with_wrappers(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sql, params, many=False, executor=self._execute
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 92, in _execute_with_wrappers
    return executor(sql, params, many, context)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 100, in _execute
    with self.db.wrap_database_errors:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/utils.py", line 91, in __exit__
    raise dj_exc_value.with_traceback(traceback) from exc_value
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 360, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
django.db.utils.OperationalError: database is locked

14:57:41 [Q] INFO Processed 'episodes.resolver.resolve_entities' (skylark-jig-lemon-july)

### Assistant

This is a known SQLite limitation — it doesn't handle concurrent writes well, and batch reprocessing causes multiple Django Q workers to write simultaneously. This isn't caused by our changes; it would happen with any batch operation.

The standard fix for Django + SQLite is to increase the database timeout so writers wait instead of failing immediately. Let me check the current setting.

No timeout configured — SQLite defaults to 5 seconds, which is too short when multiple workers are writing. Adding a longer timeout will let writers queue up instead of failing.

The SQLite timeout is now 30 seconds (up from the default 5s). When multiple workers try to write simultaneously, they'll wait up to 30s for the lock instead of failing immediately. Restart `qcluster` and the errors should be gone.

### User

In the Processing runs list page in the Django admin UI, add a column "Current Step" after the "Status" column that shows the currently running step.

### Assistant

Done. The Processing Runs list now shows a "Current step" column after "Status" that displays the currently running step name, or "—" if no step is running.
