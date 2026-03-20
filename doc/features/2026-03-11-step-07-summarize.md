# Step 7: Summarize Episode

**Date:** 2026-03-11

## Problem

After transcription (Step 6), episodes transition to `SUMMARIZING` status but nothing processes them. The pipeline needs an LLM-generated summary of each transcript to provide a concise overview of the episode content — language, topics, artists, and musical context. The summarization LLM must be independently configurable from the scraper's LLM, since different models may be preferred for structured extraction vs. free-text generation.

## Changes

- **LLMProvider base class** (`episodes/providers/base.py`): Added `generate(system_prompt, user_content) -> str` abstract method alongside the existing `structured_extract()`. This supports plain-text LLM calls without JSON schema constraints.

- **OpenAI implementation** (`episodes/providers/openai.py`): Implemented `generate()` on `OpenAILLMProvider` using `client.responses.create()` without the `text` format parameter, returning `response.output_text` directly as a string.

- **Summarization provider factory** (`episodes/providers/factory.py`): Added `get_summarization_provider()` reading from `RAGTIME_SUMMARIZATION_*` settings, completely independent from the scraper's `get_llm_provider()`. This allows using different models/keys for summarization.

- **Summarizer task** (`episodes/summarizer.py`): New task module with `summarize_episode(episode_id)` following the transcriber pattern. Validates status is `SUMMARIZING` and transcript is non-empty, calls `provider.generate()` with a jazz-focused system prompt, stores the result in `summary_generated`, and advances to `EXTRACTING`. Errors set status to `FAILED`.

- **Signal-driven chaining** (`episodes/signals.py`): Extended `queue_next_step` to detect `SUMMARIZING` status and queue the summarizer task.

- **Admin** (`episodes/admin.py`): Added `summary_generated` as a read-only field, shown in a "Summary" fieldset when populated (between Transcript and Transcript JSON).

- **Test fixtures**: Moved the two real Whisper JSON response files (`wdr-giant-steps-django-reinhardt-*` and `wdr-giant-steps-john-coltrane-*`) from the project root to `episodes/tests/fixtures/` for proper organization.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RAGTIME_SUMMARIZATION_PROVIDER` | `openai` (default) | Same provider abstraction as scraper LLM |
| `RAGTIME_SUMMARIZATION_MODEL` | `gpt-4.1-mini` (default) | Good balance of quality and cost for summarization |
| `RAGTIME_SUMMARIZATION_API_KEY` | (empty default) | Must be set in `.env`; separate from scraper key to allow different accounts |
| System prompt style | 2-4 paragraphs, no bullets | Flowing prose summary covering language, topics, artists, musical context |

## Verification

```bash
# Run all tests (55 total: 48 existing + 7 new)
uv run python manage.py test episodes -v2

# End-to-end: start server + worker, create episode via admin
uv run python manage.py runserver   # Terminal 1
uv run python manage.py qcluster   # Terminal 2

# Expected flow: ... → transcribing → summarizing → extracting
# Check admin detail view for Summary section
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `summary_generated` TextField |
| `episodes/providers/base.py` | Added `generate()` abstract method to `LLMProvider` |
| `episodes/providers/openai.py` | Implemented `generate()` on `OpenAILLMProvider` |
| `episodes/providers/factory.py` | Added `get_summarization_provider()` factory function |
| `ragtime/settings.py` | Added `RAGTIME_SUMMARIZATION_PROVIDER`, `_API_KEY`, `_MODEL` settings |
| `episodes/summarizer.py` | New — summarize task module |
| `episodes/signals.py` | Extended signal for `SUMMARIZING` status transitions |
| `episodes/admin.py` | Added `summary_generated` to readonly fields and conditional fieldset |
| `episodes/tests.py` | 7 new tests (6 summarize + 1 signal) |
| `episodes/tests/fixtures/` | Moved 2 Whisper JSON fixtures from project root |
| `episodes/migrations/0005_*.py` | Migration for `summary_generated` field |
