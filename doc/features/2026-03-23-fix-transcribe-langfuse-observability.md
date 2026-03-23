# Fix Transcription Step Missing from Langfuse Traces

**Date:** 2026-03-23

## Problem

The `transcribe_episode` pipeline step was not logging the OpenAI Whisper API request or response to Langfuse. Unlike the LLM provider methods (`structured_extract`, `generate`), the `transcribe()` method had no `@observe_provider` decorator or manual input/output logging.

## Changes

| File | Change |
|------|--------|
| `episodes/providers/openai.py` | Add `@observe_provider` decorator and `set_observation_input`/`set_observation_output` calls to `transcribe()`. Log audio filename (basename only, not full path) in input. Log a summary dict (text, duration, language, word/segment counts) instead of the full verbose_json payload. |
| `episodes/observability.py` | Extend `set_observation_input()` to support two calling conventions: chat-style (positional args for LLM providers) and dict-style (keyword args for non-chat providers). Add argument validation for chat-style (exactly 2 positional args, only `response_schema` allowed as kwarg). |
| `episodes/tests/test_observability.py` | Add `SetObservationInputTest` with 5 tests covering both calling conventions, argument validation, and metadata handling. |
| `CHANGELOG.md` | Add entry under `### Fixed` for 2026-03-23. |

## Key parameters

- **Output summary fields:** `text`, `duration`, `language`, `words_count`, `segments_count` — avoids shipping large word/segment arrays to Langfuse
- **Input sanitization:** `os.path.basename(audio_path)` logged as `audio_file` — avoids leaking filesystem paths to Langfuse

## Verification

1. Run tests: `uv run python manage.py test episodes.tests.test_observability episodes.tests.test_transcribe`
2. Process an episode with Langfuse enabled and verify the `transcribe_episode` trace shows a child `transcribe` span with input parameters and output summary
