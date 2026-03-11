# Step 7: Summarize — Implementation Plan

## Context
Steps 1-6 of the RAGtime pipeline are complete. After transcription (Step 6), episodes transition to `SUMMARIZING` status but nothing handles them. Step 7 uses an LLM to generate a free-text summary of the transcript and store it on the episode. The summarization LLM is separately configurable from the general LLM provider (used by scraper). Two real Whisper response JSON files at the project root serve as test fixtures.

## Changes

### 1. Model: add `summary_generated` field
**File:** `episodes/models.py`
- Add `summary_generated = models.TextField(blank=True, default="")` after the transcript fields
- Comment: `# LLM-generated summary (populated by summarizer)`
- Migration will be auto-generated

### 2. Provider: add `generate()` to LLMProvider
**File:** `episodes/providers/base.py`
- Add abstract method: `generate(self, system_prompt: str, user_content: str) -> str`
- Returns plain text (not JSON)

**File:** `episodes/providers/openai.py`
- Implement `generate()` on `OpenAILLMProvider` using `client.responses.create()` without JSON schema, returning `response.output_text`

### 3. Factory: add `get_summarization_provider()`
**File:** `episodes/providers/factory.py`
- Add `get_summarization_provider() -> LLMProvider` reading from:
  - `settings.RAGTIME_SUMMARIZATION_PROVIDER`
  - `settings.RAGTIME_SUMMARIZATION_API_KEY`
  - `settings.RAGTIME_SUMMARIZATION_MODEL`

### 4. Settings: add summarization config
**File:** `ragtime/settings.py`
- Add:
  ```python
  RAGTIME_SUMMARIZATION_PROVIDER = os.getenv('RAGTIME_SUMMARIZATION_PROVIDER', 'openai')
  RAGTIME_SUMMARIZATION_API_KEY = os.getenv('RAGTIME_SUMMARIZATION_API_KEY', '')
  RAGTIME_SUMMARIZATION_MODEL = os.getenv('RAGTIME_SUMMARIZATION_MODEL', 'gpt-4.1-mini')
  ```

### 5. Task: `summarize_episode()`
**File:** `episodes/summarizer.py` (new)
- Pattern follows `transcriber.py` exactly:
  1. Fetch episode, validate status == SUMMARIZING
  2. Validate transcript is non-empty
  3. Get provider via `get_summarization_provider()`
  4. Call `provider.generate(system_prompt=SUMMARIZE_SYSTEM_PROMPT, user_content=episode.transcript)` -- uses the plain-text transcript only (from `episode.transcript`, which is `whisper_response["text"]`)
  5. Store result in `episode.summary_generated`
  6. Transition status -> EXTRACTING
  7. On error: status -> FAILED with error_message
- System prompt instructs LLM to summarize a podcast transcript, noting language, key topics, artists discussed, and musical context

### 6. Signal: chain SUMMARIZING -> summarize_episode
**File:** `episodes/signals.py`
- Add `elif instance.status == Episode.Status.SUMMARIZING:` branch dispatching `async_task("episodes.summarizer.summarize_episode", instance.pk)`

### 7. Admin: display summary field
**File:** `episodes/admin.py`
- Add `summary_generated` to readonly fields and appropriate fieldset (similar to transcript)

### 8. Tests
**File:** `episodes/tests.py`
- `SummarizeEpisodeTests` class following `TranscribeEpisodeTests` pattern:
  - `test_success` -- mocks `get_summarization_provider`, verifies summary_generated stored, status -> EXTRACTING
  - `test_episode_not_found` -- nonexistent ID logs error
  - `test_wrong_status` -- episode not in SUMMARIZING status, no-op
  - `test_empty_transcript` -- fails with error message
  - `test_provider_error` -- exception -> FAILED status
  - `test_generate_method` -- verifies `generate()` called with correct prompt and transcript
- `SummarizeSignalTests` -- verifies SUMMARIZING status triggers async_task
- Use the two real Whisper JSON response files as realistic test fixtures
- **Move fixture files**: relocate the two `wdr-giant-steps-*-response.json` files from the project root to `episodes/tests/fixtures/` (create directory)
- Load fixtures in tests via `pathlib.Path(__file__).parent / "tests" / "fixtures" / "<filename>.json"`

## Files Modified
- `episodes/models.py` -- add `summary_generated` field
- `episodes/providers/base.py` -- add `generate()` abstract method
- `episodes/providers/openai.py` -- implement `generate()`
- `episodes/providers/factory.py` -- add `get_summarization_provider()`
- `ragtime/settings.py` -- add `RAGTIME_SUMMARIZATION_*` settings
- `episodes/summarizer.py` -- new task module
- `episodes/signals.py` -- add SUMMARIZING dispatch
- `episodes/admin.py` -- display summary_generated
- `episodes/tests/fixtures/` -- move the two `wdr-giant-steps-*-response.json` files from project root
- `episodes/tests.py` -- add summarize tests, update fixture loading for moved files

## Verification
1. `python manage.py makemigrations` -- generates migration for `summary` field
2. `python manage.py migrate` -- applies cleanly (adds `summary_generated` field)
3. `python manage.py test episodes` -- all existing + new tests pass
4. Manual: create episode with transcript, set status to SUMMARIZING, save -> signal fires -> summary populated
