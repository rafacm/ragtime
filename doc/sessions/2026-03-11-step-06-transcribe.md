# Session: Step 6 — Transcribe

This session planned and implemented Step 6 of the RAGtime pipeline: audio transcription using the OpenAI Whisper API with pluggable provider abstraction.

## Planning Phase

The session began in plan mode. Key files were reviewed to understand the existing codebase:

- `episodes/models.py` — Episode model with status pipeline
- `episodes/providers/base.py` — `TranscriptionProvider` ABC already defined
- `episodes/providers/openai.py` — existing `OpenAILLMProvider`
- `episodes/providers/factory.py` — existing `get_llm_provider()` factory
- `episodes/downloader.py` — reference for task pattern (status check, error handling, signal-driven chaining)
- `episodes/signals.py` — existing `queue_next_step` signal handler
- `episodes/admin.py` — existing admin with conditional fieldsets

The plan was written to `doc/plans/step-06-transcribe.md` covering 8 file changes across model fields, settings, provider, factory, task, signal, admin, and tests.

## Implementation Phase

All changes were implemented in a single pass:

1. **Model fields** — Added `transcript` (TextField) and `transcript_json` (JSONField, null=True) to `Episode`
2. **Settings** — Added `RAGTIME_TRANSCRIPTION_PROVIDER`, `_API_KEY`, `_MODEL` with sensible defaults
3. **Provider** — `OpenAITranscriptionProvider` using `client.audio.transcriptions.create()` with verbose JSON and word+segment timestamps. File handle opened/closed in try/finally. Language passed only when non-empty.
4. **Factory** — `get_transcription_provider()` mirroring `get_llm_provider()` pattern
5. **Transcriber task** — `transcribe_episode()` following downloader pattern: status guard → audio_file check → provider call → save results → advance to SUMMARIZING
6. **Signal** — Added `TRANSCRIBING` branch to `queue_next_step`
7. **Admin** — Added transcript fields to readonly_fields, conditional fieldsets (Transcript visible, Transcript JSON collapsed)
8. **Tests** — 8 new tests: success, no audio file, API error, nonexistent episode, wrong status, empty language → None, language passthrough, signal wiring

## Verification

```
$ uv run python manage.py makemigrations episodes
Migrations for 'episodes':
  episodes/migrations/0004_episode_transcript_episode_transcript_json.py

$ uv run python manage.py migrate
Applying episodes.0004_episode_transcript_episode_transcript_json... OK

$ uv run python manage.py test -v2
Ran 48 tests in 0.616s
OK
```

All 48 tests pass (40 existing + 8 new).
