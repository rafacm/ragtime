# Steps 4 & 5: Download & Resize Audio

**Date:** 2026-03-09

## Problem

After the scrape step extracts `audio_url` from a podcast page, the audio file needs to be downloaded to local storage before transcription. The Whisper API has a 25MB file size limit, so large audio files must be downsampled. There was also no mechanism to track why an episode failed.

## Changes

Two new Django Q2 task modules handle audio acquisition and resizing as separate pipeline steps:

- **Download** (`episodes/downloader.py`): Streams the audio file from `audio_url` using httpx with 64KB chunks, saves to Django's `MEDIA_ROOT/episodes/` via `FileField`. If the file is within the 25MB limit, the episode advances to `transcribing`. If larger, it advances to `resizing`.

- **Resize** (`episodes/resizer.py`): Runs ffmpeg to downsample the audio (mono, 22050Hz, 64kbps). If the output is within the limit, the episode advances to `transcribing`. If still too large, the episode is marked `failed` with a descriptive error message.

- **Signal-driven chaining**: The existing `post_save` signal (`queue_next_step`) was extended to detect status transitions to `downloading` and `resizing`, automatically queuing the corresponding task. Only `save(update_fields=...)` calls containing `"status"` trigger the signal, preventing re-trigger loops.

- **Error tracking**: A new `error_message` field on Episode stores the reason for failure, visible in the admin when status is `failed`.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_MAX_AUDIO_SIZE` | 25MB (25 * 1024 * 1024) | Whisper API file size limit |
| ffmpeg `-ac` | `1` (mono) | Speech content; stereo unnecessary |
| ffmpeg `-ar` | `22050` Hz | Sufficient for speech intelligibility |
| ffmpeg `-b:a` | `64k` | Good speech quality at low bitrate; a 2h episode ≈ 57MB → ~28MB mono 64kbps |
| `DOWNLOAD_TIMEOUT` | 600s (10 min) | Large podcast files may be slow to download |
| `FFMPEG_TIMEOUT` | 600s (10 min) | Long episodes take time to transcode |
| `CHUNK_SIZE` | 64KB | Balance between memory usage and I/O efficiency |

## Verification

```bash
# Run all tests (40 total: 25 existing + 15 new)
uv run python manage.py test episodes

# End-to-end: start server + worker, create episode via admin
uv run python manage.py runserver   # Terminal 1
uv run python manage.py qcluster   # Terminal 2

# Expected flow: pending → scraping → downloading → transcribing
# (or downloading → resizing → transcribing for large files)
# Check admin detail view for audio_file and error_message fields
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `RESIZING` status, `audio_file` FileField, `error_message` TextField |
| `ragtime/settings.py` | Added `MEDIA_ROOT`, `MEDIA_URL`, `RAGTIME_MAX_AUDIO_SIZE` |
| `episodes/downloader.py` | New — stream download + size check task |
| `episodes/resizer.py` | New — ffmpeg downsample + size validation task |
| `episodes/signals.py` | Extended `queue_next_step` for download/resize triggers |
| `episodes/admin.py` | Added `error_message` and `audio_file` to fieldsets |
| `episodes/tests.py` | 15 new tests (5 download, 7 resize, 4 signal) |
| `episodes/migrations/0003_*.py` | Migration for new fields and status |
