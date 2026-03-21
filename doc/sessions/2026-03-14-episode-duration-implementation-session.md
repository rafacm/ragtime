# Session: Episode Duration — Implementation

**Date:** 2026-03-14

**Session ID:** 83e8d60a-9faa-48cf-9575-93f7f115e1bf

## Summary

Implemented episode duration extraction from MP3 metadata and admin column reorder. Added mutagen dependency, duration model field, extraction in downloader, formatted display in admin, and fixed download tests to mock the new MP3 parsing.

## Conversation

### User

[Request interrupted by user for tool use]

Implement the following plan:

# Plan: Episode Duration & Admin Column Reorder

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


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/7f339a4a-fc60-429d-a3a5-5a6acda9935c.jsonl

### Assistant

Now I have all the context. Let me make all the changes.

Now let me install mutagen and generate the migration.

The tests fail because the test MP3 files are mock/fake files that mutagen can't parse. Let me check the test to see how they mock the download.

The tests write fake data, not real MP3 content. I need to also mock `MP3` in the downloader. The cleanest approach is to patch `episodes.downloader.MP3` in the tests that write fake audio.

All 84 tests pass. Here's a summary of the changes:

1. **`pyproject.toml`** — Added `mutagen>=1.47,<2` dependency
2. **`episodes/models.py`** — Added `duration = models.PositiveIntegerField(null=True, blank=True)` after `audio_file`
3. **`episodes/downloader.py`** — Import `MP3` from mutagen, extract duration after saving the audio file, include `"duration"` in `update_fields`
4. **`episodes/admin.py`** — Reordered `list_display` to `(title, url, language, formatted_duration, status, created_at, updated_at)`, added `formatted_duration` method with HH:MM:SS formatting, added `duration` to `readonly_fields` and the "Files" fieldset
5. **`episodes/migrations/0013_episode_duration.py`** — Auto-generated migration
6. **`episodes/tests/test_download.py`** — Patched `MP3` in the two download success tests so they work with fake audio data; also added a duration assertion to verify it's saved correctly

### User

Looks good! Create a PR

### Assistant

PR created: https://github.com/rafacm/ragtime/pull/38

### User

The documentation as per the instructions in the AGENTS.md file is missing in the PR.

### Assistant

Let me check what documentation already exists and the reference format.

Let me also check the planning session transcript to get the session ID, and see the reference format.

Now I need to check if there's a planning session transcript for this feature. The plan was created in a previous conversation — let me check that transcript.

The planning session is in `7f339a4a-fc60-429d-a3a5-5a6acda9935c`. Let me extract the key conversation turns to build the transcripts. Let me read more of it.

Good, I have all the context. Now let me also check what the agent explored during planning.

Now I have everything. Let me create all the documentation files.

Now update the CHANGELOG.

Now commit and push the documentation.

Done. Pushed the documentation commit to the PR with:

- **Plan**: `doc/plans/episode-duration.md`
- **Feature doc**: `doc/features/episode-duration.md`
- **Planning session**: `doc/sessions/2026-03-14-episode-duration-planning-session.md`
- **Implementation session**: `doc/sessions/2026-03-14-episode-duration-implementation-session.md`
- **CHANGELOG.md**: Added entry under 2026-03-14 → Added

PR: https://github.com/rafacm/ragtime/pull/38
