# Plan: Merge Resize into Transcribe

## Context

The `resizing` pipeline step exists solely to satisfy the Whisper API's 25MB file size limit. It's a transcription provider implementation detail, not a meaningful domain event. Absorbing it into the transcribe step reduces the pipeline from 11 to 10 steps, simplifies the download step (no more conditional branching), and removes a status/module that doesn't carry its weight.

## Changes

### 1. `episodes/models.py` — Remove RESIZING
- Delete `RESIZING = "resizing"` from `Status` enum
- Remove `Episode.Status.RESIZING` from `PIPELINE_STEPS`

### 2. Migration — Handle existing data
- Data migration: move any episodes with `status='resizing'` → `'transcribing'`
- Mark orphaned `ProcessingStep(step_name='resizing')` as `SKIPPED` if still pending/running
- `AlterField` on `Episode.status` to reflect new choices

### 3. `episodes/transcriber.py` — Add resize logic
- Add `_resize_if_needed(episode)` helper (extracted from `resizer.py`):
  - Check file size vs `RAGTIME_MAX_AUDIO_SIZE` (25MB default)
  - If over: check ffmpeg available, run ffmpeg (`-ac 1 -ar 22050 -b:a 64k`), validate output size, replace `episode.audio_file`
  - Returns `True` if resize happened (so `update_fields` includes `audio_file`)
- Call `_resize_if_needed` at the start of `transcribe_episode`, before provider call

### 4. `episodes/downloader.py` — Simplify
- Remove file-size check and conditional branching
- Always: `complete_step(DOWNLOADING)` → `status = TRANSCRIBING`
- Remove `skip_step` import, `settings` import, and size-related variables

### 5. `episodes/signals.py` — Remove RESIZING dispatch
- Delete the `elif instance.status == Episode.Status.RESIZING` branch

### 6. Delete `episodes/resizer.py`

### 7. Tests
- **Delete** `episodes/tests/test_resize.py`
- **Update** `test_download.py`: large-file test now expects `TRANSCRIBING` (not `RESIZING`), remove size-threshold override
- **Update** `test_transcribe.py`: add tests for resize-within-transcribe (large file resized, still too large → fail, no ffmpeg → fail, ffmpeg error → fail, small file skips resize)
- **Update** `test_signals.py`: remove resize signal test

### 8. Documentation
- **README.md**: Remove Resize subsection, renumber steps 5–11 → 4–10, mention ffmpeg downsampling in Transcribe description, update intro step count
- **CLAUDE.md**: Update "11-step" → "10-step", remove `resize` from status flow
- **CHANGELOG.md**: Add entry under 2026-03-15

## File summary

| File | Action |
|------|--------|
| `episodes/models.py` | Modify |
| `episodes/migrations/0015_remove_resizing_status.py` | Create |
| `episodes/transcriber.py` | Modify |
| `episodes/downloader.py` | Modify |
| `episodes/signals.py` | Modify |
| `episodes/resizer.py` | Delete |
| `episodes/tests/test_resize.py` | Delete |
| `episodes/tests/test_download.py` | Modify |
| `episodes/tests/test_transcribe.py` | Modify |
| `episodes/tests/test_signals.py` | Modify |
| `README.md` | Modify |
| `CLAUDE.md` | Modify |
| `CHANGELOG.md` | Modify |

## Verification
1. `uv run python manage.py makemigrations --check` — no pending migrations
2. `uv run python manage.py migrate` — migration applies cleanly
3. `uv run python manage.py test episodes` — all tests pass
4. `uv run python manage.py check` — no Django system check errors
