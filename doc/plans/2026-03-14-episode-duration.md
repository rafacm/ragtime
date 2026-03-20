# Plan: Episode Duration & Admin Column Reorder

**Date:** 2026-03-14

## Context

The Episodes list in the Django admin needs reordering and a new "duration" column showing episode length in HH:MM:SS format. Duration should be extracted from the downloaded MP3 file.

## Changes

### 1. Add `mutagen` dependency (`pyproject.toml`)

Add `mutagen>=1.47,<2` to dependencies. Mutagen is a lightweight, pure-Python audio metadata library that can read MP3 duration without ffmpeg.

### 2. Add `duration` field to Episode model (`episodes/models.py`)

Add `duration = models.PositiveIntegerField(null=True, blank=True)` after the `audio_file` field. Stores total seconds as an integer. Null when not yet downloaded.

### 3. Extract duration after download (`episodes/downloader.py`)

After saving the audio file to the FileField (line 48), use `mutagen.mp3.MP3` to read the duration from the saved file and set `episode.duration`. Add `"duration"` to the `save(update_fields=...)` call on line 67.

```python
from mutagen.mp3 import MP3
audio = MP3(episode.audio_file.path)
episode.duration = int(audio.info.length)
```

### 4. Update admin list_display (`episodes/admin.py`)

Change `list_display` to:
```python
list_display = ("title", "url", "language", "formatted_duration", "status", "created_at", "updated_at")
```

Add a custom display method:
```python
@admin.display(description="Duration", ordering="duration")
def formatted_duration(self, obj):
    if obj.duration is None:
        return "—"
    hours, remainder = divmod(obj.duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
```

Add `duration` to `readonly_fields`. Add it to the "Files" fieldset (or show alongside audio_file).

### 5. Generate migration

Run `uv run python manage.py makemigrations episodes`.

## Files to modify

| File | Change |
|---|---|
| `pyproject.toml` | Add `mutagen` dependency |
| `episodes/models.py` | Add `duration` field |
| `episodes/downloader.py` | Extract duration from MP3 after download |
| `episodes/admin.py` | Reorder `list_display`, add `formatted_duration` method, add `duration` to readonly and fieldsets |
| New migration file | Auto-generated |

## Verification

1. `uv sync` — install mutagen
2. `uv run python manage.py makemigrations && uv run python manage.py migrate`
3. `uv run python manage.py test episodes` — run existing tests
4. `uv run python manage.py runserver` — check admin Episodes list shows columns in order: Title, URL, Language, Duration, Status, Created at, Updated at
