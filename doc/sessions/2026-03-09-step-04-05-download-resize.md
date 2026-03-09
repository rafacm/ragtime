# Session: Steps 4 & 5 — Download & Resize Audio

**Date:** 2026-03-09

## Summary

Implemented Steps 4 (Download) and 5 (Resize) of the RAGtime ingestion pipeline. These steps handle downloading podcast audio files from URLs extracted during scraping, and conditionally downsampling large files to fit within the Whisper API's 25MB limit.

## Conversation

### User
Let's plan the implementation for Steps 4 and 5 in README.md file together.

### Assistant
Entered plan mode. Read README.md, the Step 3 plan, and explored the codebase (models, scraper, signals, admin, tests, settings) to understand existing patterns.

### Design Questions & Answers

**Q1: Single task or two separate tasks?**
A: Two separate tasks with an additional `resizing` status. If after resizing the audio file is still bigger than 25MB, status → `failed` with reason.

**Q2: How should downloaded audio files be stored?**
A: `MEDIA_ROOT/episodes/` with Django FileField.

**Q3: ffmpeg downsampling strategy?**
A: Mono 64kbps, 22050Hz.

**Q4: How should the download task be triggered?**
A: Signal on status change (extend existing `post_save` signal).

**Q5: Should we add an error_message field?**
A: Yes — add `error_message` TextField to Episode.

### Implementation

Plan was written and approved. Implementation proceeded:

1. **Model changes** — Added `RESIZING` status, `audio_file` FileField, `error_message` TextField
2. **Settings** — Added `MEDIA_ROOT`, `MEDIA_URL`, `RAGTIME_MAX_AUDIO_SIZE`
3. **downloader.py** — New module: stream-downloads audio via httpx, saves to FileField, routes by file size
4. **resizer.py** — New module: ffmpeg downsample (mono, 22050Hz, 64kbps), validates output size
5. **signals.py** — Extended `queue_next_step` to trigger download on `downloading` status and resize on `resizing` status
6. **admin.py** — Shows `error_message` when failed, `audio_file` in Files fieldset
7. **Migration** — Generated and applied `0003_episode_audio_file_episode_error_message_and_more`
8. **Tests** — 15 new tests (5 download, 7 resize, 4 signal). All 40 tests pass.

### Key Design Decisions

- **Two tasks, not one**: Download and resize are separate Q2 tasks with distinct statuses (`downloading` → `resizing`), allowing independent retry and clearer status tracking.
- **Signal-driven chaining**: Status changes to `downloading` or `resizing` via `save(update_fields=...)` trigger the next task automatically. The download task avoids re-saving `downloading` status to prevent re-trigger loops.
- **Fail-fast on resize**: If the file is still >25MB after aggressive downsampling (mono, 64kbps), it's marked `failed` rather than attempting further reduction — the content is likely too long for the Whisper API.
- **Error tracking**: `error_message` field provides admin-visible failure reasons, improving debuggability over log-only errors.
