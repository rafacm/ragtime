# Step 6: Transcribe Audio

**Date:** 2026-03-11

## Problem

After downloading (and optionally resizing) episode audio, the pipeline needs to convert audio into text with timestamps. This enables full-text search, entity extraction in later steps, and "skip to timestamp" functionality in the UI. The transcription backend must be pluggable to support different providers.

## Changes

- **Transcription provider** (`episodes/providers/openai.py`): Added `OpenAITranscriptionProvider` implementing the `TranscriptionProvider` abstract base class. Calls `client.audio.transcriptions.create()` with `response_format="verbose_json"` and `timestamp_granularities=["word", "segment"]` to get both segment-level and word-level timestamps. The `language` parameter is only passed when non-empty, allowing Whisper to auto-detect otherwise. Returns `response.model_dump()` to convert the Pydantic response into a plain dict for Django's `JSONField`.

- **Provider factory** (`episodes/providers/factory.py`): Added `get_transcription_provider()` following the same pattern as `get_llm_provider()`. Reads `RAGTIME_TRANSCRIPTION_*` settings, validates the API key is set, and lazily imports/returns the provider.

- **Transcriber task** (`episodes/transcriber.py`): New task module with `transcribe_episode(episode_id)` following the downloader/resizer pattern. Validates status is `TRANSCRIBING` and `audio_file` exists, calls the provider, stores results in `transcript` (plain text) and `transcript_json` (full Whisper response), then advances to `SUMMARIZING`. Errors set status to `FAILED` with the error message.

- **Signal-driven chaining** (`episodes/signals.py`): Extended `queue_next_step` to detect status transitions to `TRANSCRIBING` and queue the transcriber task.

- **Admin** (`episodes/admin.py`): Added `transcript` and `transcript_json` as read-only fields. Transcript is shown in a visible fieldset when populated; transcript JSON is shown collapsed.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_TRANSCRIPTION_PROVIDER` | `openai` (default) | Whisper API via OpenAI is the primary backend |
| `RAGTIME_TRANSCRIPTION_MODEL` | `whisper-1` (default) | Only Whisper model currently available via OpenAI API |
| `response_format` | `verbose_json` | Required to get segment and word timestamps |
| `timestamp_granularities` | `["word", "segment"]` | Word-level for precise "skip to" links; segment-level for chunking in step 10 |
| `transcript_json` null | `NULL` not `{}` | Distinguishes "not yet transcribed" from "transcribed but empty" |

## Verification

```bash
# Run all tests (48 total: 40 existing + 8 new)
uv run python manage.py test episodes -v2

# End-to-end: start server + worker, create episode via admin
uv run python manage.py runserver   # Terminal 1
uv run python manage.py qcluster   # Terminal 2

# Expected flow: ... → downloading → transcribing → summarizing
# Check admin detail view for transcript and transcript JSON sections
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `transcript` TextField and `transcript_json` JSONField |
| `ragtime/settings.py` | Added `RAGTIME_TRANSCRIPTION_PROVIDER`, `_API_KEY`, `_MODEL` settings |
| `episodes/providers/openai.py` | Added `OpenAITranscriptionProvider` class |
| `episodes/providers/factory.py` | Added `get_transcription_provider()` factory function |
| `episodes/transcriber.py` | New — transcribe task module |
| `episodes/signals.py` | Extended signal for `TRANSCRIBING` status transitions |
| `episodes/admin.py` | Added transcript fields to readonly_fields and conditional fieldsets |
| `episodes/tests.py` | 8 new tests (7 transcribe + 1 signal) |
| `episodes/migrations/0004_*.py` | Migration for transcript and transcript_json fields |
