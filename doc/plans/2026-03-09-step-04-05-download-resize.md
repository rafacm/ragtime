# Steps 4 & 5: Download & Resize Audio

**Date:** 2026-03-09

## Goal

Download the audio file from `episode.audio_url` to local storage and, if the file exceeds the 25MB Whisper API limit, downsample it with ffmpeg. Introduce `error_message` on Episode for failure tracking.

## Decisions

| Question | Answer |
|----------|--------|
| Task structure | Two separate tasks: `download_episode` and `resize_episode` |
| New status | `RESIZING = "resizing"` between `DOWNLOADING` and `TRANSCRIBING` |
| File storage | `MEDIA_ROOT/episodes/` via Django `FileField` |
| File naming | `{episode_pk}.mp3` |
| Resize strategy | Mono (`-ac 1`), 22050Hz (`-ar 22050`), 64kbps (`-b:a 64k`) via ffmpeg subprocess |
| Post-resize too large | Status → `failed`, error_message explains size |
| Error tracking | New `error_message` TextField on Episode model |
| Task trigger | `post_save` signal on status change (extends existing signal) |
| Download method | `httpx.stream()` with 64KB chunks for memory efficiency |
| Timeouts | 10 minutes for both download and ffmpeg |

## Architecture

### Status Transitions

```
downloading → resizing       (download complete, file > 25MB)
downloading → transcribing   (download complete, file ≤ 25MB)
downloading → failed         (HTTP error, invalid audio, etc.)

resizing → transcribing      (resize complete, file ≤ 25MB)
resizing → failed            (file still > 25MB after resize, or ffmpeg error)
```

### Signal Flow

```
scrape_episode() success
  → episode.status = "downloading"
  → episode.save(update_fields=["status", ...])
    → post_save signal detects status="downloading"
      → async_task("episodes.downloader.download_episode", pk)
        → stream download audio_url → save to FileField
        → if size ≤ 25MB:
            episode.status = "transcribing"
        → if size > 25MB:
            episode.status = "resizing"
            → post_save signal detects status="resizing"
              → async_task("episodes.resizer.resize_episode", pk)
                → ffmpeg downsample → check size
                → if ≤ 25MB: status = "transcribing"
                → if > 25MB: status = "failed"
```

### Important: Avoiding Re-triggers

The download task does NOT re-save status as `downloading` (it's already in that status from the scraper). This prevents the signal from re-queuing the download task in a loop.

## Implementation Steps

### 1. Update Episode model

- Add `RESIZING = "resizing"` status
- Add `audio_file = FileField(upload_to="episodes/", blank=True)`
- Add `error_message = TextField(blank=True, default="")`

### 2. Update settings

- Add `MEDIA_ROOT = BASE_DIR / "media"`
- Add `MEDIA_URL = "/media/"`
- Add `RAGTIME_MAX_AUDIO_SIZE = 25 * 1024 * 1024`

### 3. Create `episodes/downloader.py`

- `download_episode(episode_id)` — stream-download, save to FileField, route by size

### 4. Create `episodes/resizer.py`

- `resize_episode(episode_id)` — ffmpeg downsample, check output size, fail if still too large

### 5. Update signals

- Extend `queue_next_step` to trigger download on `downloading` and resize on `resizing`
- Only trigger on `save(update_fields=...)` containing `"status"` to avoid spurious triggers

### 6. Update admin

- Show `error_message` in main section when failed
- Show `audio_file` in a "Files" fieldset when present

### 7. Generate migration, write tests

## Files Modified/Created

| File | Change |
|------|--------|
| `episodes/models.py` | Add `RESIZING` status, `audio_file` FileField, `error_message` TextField |
| `ragtime/settings.py` | Add `MEDIA_ROOT`, `MEDIA_URL`, `RAGTIME_MAX_AUDIO_SIZE` |
| `episodes/downloader.py` | **New** — `download_episode()` task |
| `episodes/resizer.py` | **New** — `resize_episode()` task |
| `episodes/signals.py` | Extend to trigger download/resize on status changes |
| `episodes/admin.py` | Add new fields to fieldsets |
| `episodes/tests.py` | 15 new tests for downloader, resizer, signals |
| `episodes/migrations/0003_*.py` | Generated migration |

## Environment Variables

No new environment variables. `RAGTIME_MAX_AUDIO_SIZE` is a Django setting (not user-configurable via env).

## Verification

1. Start dev server + Q2 worker
2. Create an episode with a podcast URL that has an audio file
3. Episode should progress: `pending` → `scraping` → `downloading` → `transcribing` (or `→ resizing → transcribing`)
4. Check admin: `audio_file` field shows the saved file path
5. Verify file exists on disk at `media/episodes/{pk}.mp3`
6. Run `uv run python manage.py test episodes` — all 40 tests pass
