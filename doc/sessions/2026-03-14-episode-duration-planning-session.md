# Session: Episode Duration — Planning

**Session ID:** `7f339a4a-fc60-429d-a3a5-5a6acda9935c`

**Date:** 2026-03-14

## Summary

Planned the addition of an episode duration field extracted from MP3 metadata and reordering of admin list columns. Explored the codebase to understand the Episode model, download pipeline, and admin configuration, then produced a 5-step implementation plan.

## Conversation

### User

In the Episodes list in the Django admin interface, we want the first column to be "Title", then the URL, then the language, then the episode length in hours minutes and seconds, then the status, and finally the created and last updated columns. The episode length should be added to the Episode model and after the episode is downloaded the information about the length should be extracted from the downloaded MP3 file.

### Assistant

Explored the codebase to understand current state:

- Read `episodes/models.py` — found the Episode model with `audio_file = models.FileField(upload_to="episodes/")`, no existing duration field.
- Read `episodes/admin.py` — found `list_display = ("url", "title", "language", "status", "created_at")`, URL is the first column.
- Read `episodes/downloader.py` — found the download function saves the MP3 via `episode.audio_file.save()` then checks file size. The save call on line 67 uses `update_fields=["status", "audio_file", "updated_at"]`.
- Checked `pyproject.toml` — no existing audio metadata libraries.

Considered two approaches for reading MP3 duration:
1. **ffmpeg/ffprobe** — already a project dependency for resizing, but requires subprocess call and parsing output.
2. **mutagen** — pure-Python, lightweight, purpose-built for audio metadata. Can read duration with `MP3(path).info.length`.

Chose mutagen because it's simpler, doesn't require parsing subprocess output, and is a well-maintained library specifically designed for this use case.

Decided on `PositiveIntegerField` over `DurationField` for storage — integer seconds is sufficient precision and avoids Django's `timedelta` serialization. The display formatting (HH:MM:SS vs MM:SS) is handled by a custom admin method.

Wrote the plan with 5 steps: add dependency, add model field, extract after download, update admin, generate migration.
