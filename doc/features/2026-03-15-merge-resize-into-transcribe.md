# Feature: Merge Resize into Transcribe

**Date:** 2026-03-15

## Problem

The `resizing` pipeline step existed solely to satisfy the Whisper API's 25 MB file-size limit. It was a transcription provider implementation detail, not a meaningful domain event. Having it as a separate step added:

- An extra status value (`resizing`) and signal dispatch branch
- Conditional branching in the downloader (check size, skip or queue resize)
- A standalone module (`resizer.py`) with its own test file
- An 11th pipeline step in documentation

## Changes

| File | Change |
|------|--------|
| `episodes/models.py` | Removed `RESIZING` from `Status` enum and `PIPELINE_STEPS` |
| `episodes/migrations/0015_remove_resizing_status.py` | Data migration (resizing→transcribing episodes, skipped processing steps) + `AlterField` |
| `episodes/transcriber.py` | Added `_resize_if_needed(episode)` helper: checks file size, runs ffmpeg if needed, returns bool for `audio_file` save |
| `episodes/downloader.py` | Removed size check, `skip_step` call, `settings` import; always transitions to `TRANSCRIBING` |
| `episodes/signals.py` | Removed `RESIZING` dispatch branch |
| `episodes/resizer.py` | Deleted |
| `episodes/tests/test_resize.py` | Deleted |
| `episodes/tests/test_download.py` | Updated large-file test to expect `TRANSCRIBING`; removed `override_settings` for size |
| `episodes/tests/test_transcribe.py` | Added `ResizeWithinTranscribeTests` class with 5 tests: small file skips resize, large file resized, still too large → fail, no ffmpeg → fail, ffmpeg error → fail |
| `episodes/tests/test_signals.py` | Removed resize signal test, renamed class to `DownloadSignalTests` |
| `README.md` | Removed Resize subsection, renumbered steps 4–10, added ffmpeg mention in Transcribe description |
| `CLAUDE.md` | Updated "11-step" → "10-step", removed `resize` from status flow |
| `CHANGELOG.md` | Added entry under 2026-03-15 |

## Key parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `RAGTIME_MAX_AUDIO_SIZE` | 25 MB (default) | Whisper API file-size limit |
| `FFMPEG_TIMEOUT` | 600s (10 min) | Generous timeout for large audio downsampling |
| ffmpeg flags | `-ac 1 -ar 22050 -b:a 64k` | Mono, low sample rate, low bitrate — maximizes compression for speech |

## Verification

1. `uv run python manage.py makemigrations --check` — no pending migrations
2. `uv run python manage.py migrate` — migration applies cleanly
3. `uv run python manage.py test episodes` — all 91 tests pass
4. `uv run python manage.py check` — no Django system check errors
