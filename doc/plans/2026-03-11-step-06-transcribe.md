# Step 6: Transcribe — Implementation Plan

**Date:** 2026-03-11

## Context

Episodes flow through a status pipeline. After download/resize (steps 4-5), audio files are ready for transcription. This step calls the OpenAI Whisper API to produce a transcript with segment and word-level timestamps, enabling future "skip to timestamp" functionality.

## Changes

### 1. Model fields + migration — `episodes/models.py`

Add after `scraped_html`:

```python
# Transcription (populated by transcriber)
transcript = models.TextField(blank=True, default="")
transcript_json = models.JSONField(blank=True, null=True)
```

- `transcript`: plain text for display/search
- `transcript_json`: full Whisper verbose JSON (segments + word timestamps); `null=True` so untranscribed episodes store `NULL` not `{}`

Run `uv run python manage.py makemigrations episodes`.

### 2. Settings — `ragtime/settings.py`

Add after `RAGTIME_MAX_AUDIO_SIZE`:

```python
# Transcription
RAGTIME_TRANSCRIPTION_PROVIDER = os.getenv('RAGTIME_TRANSCRIPTION_PROVIDER', 'openai')
RAGTIME_TRANSCRIPTION_API_KEY = os.getenv('RAGTIME_TRANSCRIPTION_API_KEY', '')
RAGTIME_TRANSCRIPTION_MODEL = os.getenv('RAGTIME_TRANSCRIPTION_MODEL', 'whisper-1')
```

### 3. Provider — `episodes/providers/openai.py`

Add `OpenAITranscriptionProvider` class:

- Opens audio file in binary mode, calls `client.audio.transcriptions.create()` with `response_format="verbose_json"` and `timestamp_granularities=["word", "segment"]`
- Passes `language` only when non-empty (Whisper auto-detects otherwise)
- Returns `response.model_dump()` (Pydantic → plain dict for JSONField)

### 4. Factory — `episodes/providers/factory.py`

Add `get_transcription_provider()` following `get_llm_provider()` pattern:

- Reads `RAGTIME_TRANSCRIPTION_PROVIDER`, `RAGTIME_TRANSCRIPTION_API_KEY`, `RAGTIME_TRANSCRIPTION_MODEL`
- Validates API key is set
- Lazy-imports and returns `OpenAITranscriptionProvider`

### 5. Task — `episodes/transcriber.py` (new file)

`transcribe_episode(episode_id)` following downloader/resizer pattern:

1. Fetch episode, verify status is `TRANSCRIBING`
2. Check `audio_file` exists
3. Get provider via factory, call `provider.transcribe(episode.audio_file.path, language=language)`
4. Store `result` in `transcript_json`, `result["text"]` in `transcript`
5. Set status → `SUMMARIZING`
6. On error: `error_message` + status → `FAILED`

### 6. Signal — `episodes/signals.py`

Add branch after `RESIZING`:

```python
elif instance.status == Episode.Status.TRANSCRIBING:
    async_task("episodes.transcriber.transcribe_episode", instance.pk)
```

### 7. Admin — `episodes/admin.py`

- Add `"transcript"`, `"transcript_json"` to `readonly_fields`
- Add conditional fieldsets: "Transcript" section (visible) when transcript exists, "Transcript JSON" section (collapsed) when transcript_json exists

### 8. Tests — `episodes/tests.py`

`TranscribeEpisodeTests` class with:
- `test_success` — mock provider returns sample verbose JSON; assert status=SUMMARIZING, transcript and transcript_json saved
- `test_no_audio_file_fails` — assert FAILED status
- `test_api_error_sets_failed` — mock provider raises; assert FAILED
- `test_nonexistent_episode` — no crash
- `test_wrong_status_skips` — status unchanged
- `test_empty_language_passes_none` — provider called with `language=None`
- `test_language_passed_to_provider` — provider called with `language="en"`
- Signal test: status change to TRANSCRIBING queues the task

## File list

| File | Action |
|------|--------|
| `episodes/models.py` | Edit — add 2 fields |
| `ragtime/settings.py` | Edit — add 3 settings |
| `episodes/providers/openai.py` | Edit — add `OpenAITranscriptionProvider` |
| `episodes/providers/factory.py` | Edit — add `get_transcription_provider()` |
| `episodes/transcriber.py` | **New** — task module |
| `episodes/signals.py` | Edit — add 1 elif branch |
| `episodes/admin.py` | Edit — readonly_fields + fieldsets |
| `episodes/tests.py` | Edit — add test class |

## Verification

```bash
uv run python manage.py makemigrations episodes
uv run python manage.py migrate
uv run python manage.py test -v2
```
