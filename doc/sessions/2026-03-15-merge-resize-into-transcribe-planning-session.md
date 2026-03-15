# Session: Merge Resize Step into Transcribe Step — Planning

**Session ID:** ab6c3b6c-4c8f-4c92-ada2-1c5485876d45

**Date:** 2026-03-15

## Summary

Planned the refactoring to merge the `resize` pipeline step into the `transcribe` step. The resize step exists solely to satisfy the Whisper API's 25MB file size limit — a transcription provider implementation detail, not a meaningful domain event. The plan absorbs resize logic into the transcriber, removes the `RESIZING` status, simplifies the downloader, and reduces the pipeline from 11 to 10 steps.

## Conversation

### User

Let's review the following steps: download, resize and transcribe. Somewhere in those steps we are also extracting the episode length. My gut feeling is that the "resize" step is actually too small of a step (implementation detail) of the Transcribe step. Propose a refactoring of these steps with pros/cons.

### Assistant

Read `episodes/pipeline.py` to understand the pipeline structure. Searched for duration/length extraction functions across the `episodes` directory. Read `episodes/downloader.py`, `episodes/resizer.py`, and `episodes/transcriber.py` in full. Then searched the `Status` enum and related constants in `episodes/models.py`, searched pipeline orchestration patterns, task registration, and signal dispatch for `resize_episode`, `download_episode`, and `transcribe_episode`.

With that full picture in hand, produced the following analysis:

---

## Current state

- **Download** (`downloader.py`): Downloads audio, extracts duration via `mutagen`, checks file size against 25MB Whisper limit. If small enough → skips resize and jumps to transcribing. If too large → sets status to resizing.
- **Resize** (`resizer.py`): Runs ffmpeg to downsample (mono, 22050Hz, 64kbps). Replaces the audio file. Transitions to transcribing.
- **Transcribe** (`transcriber.py`): Sends audio file to transcription provider, saves result.

Duration extraction already happens in `download`, not in resize or transcribe. Resize is conditionally skipped (via `skip_step`) when the file is already small enough.

---

## Option A: Merge resize into transcribe

Resize becomes an internal concern of the transcribe step — "prepare the audio and transcribe it."

| | |
|---|---|
| **Pros** | Resize exists solely to satisfy Whisper's 25MB limit — it's a transcription constraint, not a meaningful domain step. Reduces pipeline from 11 to 10 steps. Removes the conditional skip logic from download. Simplifies signals (no `RESIZING` status to dispatch on). Single file/module owns the full "audio → text" responsibility. |
| **Cons** | The transcribe step becomes longer-running and does two things (ffmpeg + API call). Harder to distinguish "failed during resize" vs "failed during transcription" in the status alone (though `error_message` still captures it). Slightly larger module. |

## Option B: Merge resize into download

Download becomes "fetch and normalize audio" — delivers a file that's guaranteed ready for transcription.

| | |
|---|---|
| **Pros** | Download already inspects the file size and makes the resize decision. Keeps transcribe clean and focused. |
| **Cons** | Download would do too much: network I/O + ffmpeg processing. These have very different failure modes and timeouts (60s vs 600s). Conceptually, downloading and audio processing are distinct concerns. |

## Option C: Keep all three steps as-is

| | |
|---|---|
| **Pros** | Each step has a single responsibility. Clear status tracking for monitoring/debugging. Resize can be retried independently. |
| **Cons** | Resize is never a meaningful domain event — it's a provider implementation detail (Whisper's size limit). The conditional skip adds complexity to download. 11 steps is a lot; this one doesn't carry its weight. If we switch to a provider without the 25MB limit, this step is dead code. |

---

## Recommendation

**Option A (merge resize into transcribe)** is the strongest choice. The resize exists only because of the transcription provider's constraint, so it belongs with transcription. The transcribe module would check file size, run ffmpeg if needed, then call the provider — all under a single `TRANSCRIBING` status. The `RESIZING` status and `skip_step` logic go away, and download becomes simpler.

### User

Yes please, plan this refactoring.

### Assistant

Entered plan mode. Launched a sub-agent to explore the pipeline signals and models in depth — reading the `Status` enum and `PIPELINE_STEPS` list in `episodes/models.py`, the signal dispatch logic in `episodes/signals.py`, the processing helpers in `episodes/processing.py`, the README pipeline documentation, test files for download/resize/transcribe/signals, and the CHANGELOG.

With the full architecture confirmed, launched a second sub-agent to draft the implementation plan, incorporating:

- Current status flow: `PENDING → SCRAPING → NEEDS_REVIEW → DOWNLOADING → RESIZING → TRANSCRIBING → SUMMARIZING → CHUNKING → EXTRACTING → RESOLVING → EMBEDDING → READY (or FAILED)`
- `PIPELINE_STEPS` list including `RESIZING`
- Signal dispatch: `RESIZING` → `episodes.resizer.resize_episode`, `TRANSCRIBING` → `episodes.transcriber.transcribe_episode`
- Download conditional: file ≤ 25MB → `complete_step(DOWNLOADING)`, `skip_step(RESIZING)`, status → `TRANSCRIBING`; file > 25MB → `complete_step(DOWNLOADING)`, status → `RESIZING`
- Test coverage: 5 download tests, 6 resize tests, 7 transcribe tests, signal tests for RESIZING dispatch

Then read `episodes/models.py` (top 30 lines) and `episodes/signals.py` in full to verify the exact status values and signal handler structure before finalising.

Produced the plan:

### Plan: Merge Resize into Transcribe

**Context:** The `resizing` pipeline step exists solely to satisfy the Whisper API's 25MB file size limit. It's a transcription provider implementation detail, not a meaningful domain event. Absorbing it into the transcribe step reduces the pipeline from 11 to 10 steps, simplifies the download step (no more conditional branching), and removes a status/module that doesn't carry its weight.

**Changes:**

1. `episodes/models.py` — Remove `RESIZING` from `Status` enum and `PIPELINE_STEPS`
2. Migration — Data migration for existing `resizing` episodes → `transcribing`, mark orphaned `ProcessingStep(step_name='resizing')` as `SKIPPED`, `AlterField` on status
3. `episodes/transcriber.py` — Add `_resize_if_needed(episode)` helper extracted from `resizer.py`
4. `episodes/downloader.py` — Remove file-size check and conditional branching, always transition to `TRANSCRIBING`
5. `episodes/signals.py` — Delete the `RESIZING` dispatch branch
6. Delete `episodes/resizer.py`
7. Tests — Delete `test_resize.py`, update `test_download.py`, `test_transcribe.py`, `test_signals.py`
8. Documentation — Update README.md, CLAUDE.md, CHANGELOG.md

**File summary:** 13 files (3 delete, 7 modify, 1 create migration, 2 docs update)

**Verification:** `makemigrations --check`, `migrate`, `test episodes`, `check`
