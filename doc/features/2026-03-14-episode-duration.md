# Feature: Episode Duration & Admin Column Reorder

**Date:** 2026-03-14

## Problem

The Episodes admin list displayed columns in a suboptimal order (URL first, then Title) and lacked any indication of episode length. Episode duration is useful for at-a-glance triage and is readily available from the downloaded MP3 file's metadata.

## Changes

- **`pyproject.toml`**: Added `mutagen>=1.47,<2` dependency. Mutagen is a pure-Python audio metadata library that reads MP3 duration without requiring ffmpeg.

- **`episodes/models.py`**: Added `duration = models.PositiveIntegerField(null=True, blank=True)` after `audio_file`. Stores total seconds as an integer. Null when the episode hasn't been downloaded yet.

- **`episodes/downloader.py`**: After saving the audio file to the FileField, reads duration via `mutagen.mp3.MP3` and sets `episode.duration = int(audio.info.length)`. Added `"duration"` to `save(update_fields=...)`.

- **`episodes/admin.py`**: Reordered `list_display` to `(title, url, language, formatted_duration, status, created_at, updated_at)`. Added `formatted_duration` method with `@admin.display(description="Duration", ordering="duration")` that renders HH:MM:SS (or MM:SS for sub-hour episodes), showing "—" when null. Added `duration` to `readonly_fields` and the "Files" fieldset alongside `audio_file`.

- **`episodes/tests/test_download.py`**: Updated `test_success_small_file` and `test_large_file_triggers_resize` to mock `episodes.downloader.MP3` (test files contain fake data, not valid MP3). Added assertion verifying `episode.duration` is saved correctly (truncated to int).

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `duration` field type | `PositiveIntegerField` | Integer seconds is sufficient precision; avoids DurationField serialization complexity |
| `null=True, blank=True` | Nullable | Duration unknown until MP3 is downloaded |
| Duration display | HH:MM:SS or MM:SS | Omits hours prefix for short episodes to reduce visual noise |

## Verification

```bash
uv sync                                # Install mutagen
uv run python manage.py migrate        # Apply migration
uv run python manage.py test episodes  # 84 tests pass
uv run python manage.py runserver      # Admin list: Title, URL, Language, Duration, Status, Created at, Updated at
```

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added `mutagen>=1.47,<2` dependency |
| `uv.lock` | Updated lockfile with mutagen |
| `episodes/models.py` | Added `duration` field |
| `episodes/downloader.py` | Import `MP3`, extract duration after download, include in `update_fields` |
| `episodes/admin.py` | Reordered `list_display`, added `formatted_duration` method, added `duration` to readonly and fieldset |
| `episodes/tests/test_download.py` | Mock `MP3` in download tests, assert duration saved |
| `episodes/migrations/0013_episode_duration.py` | Auto-generated migration |
