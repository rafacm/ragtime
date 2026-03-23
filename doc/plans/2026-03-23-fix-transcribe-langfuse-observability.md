# Fix Transcription Step Missing from Langfuse Traces

**Date:** 2026-03-23

## Problem

The `transcribe_episode` pipeline step does not log the actual OpenAI transcription API request or response to Langfuse. The `OpenAITranscriptionProvider.transcribe()` method lacks the `@observe_provider` decorator and `set_observation_input`/`set_observation_output` calls that the LLM provider methods have. The Langfuse OpenAI wrapper does not auto-instrument `audio.transcriptions.create()`.

## Plan

1. Add `@observe_provider` decorator to `OpenAITranscriptionProvider.transcribe()`
2. Call `set_observation_input()` with request parameters (model, audio file, language, format)
3. Call `set_observation_output()` with a summary of the Whisper response (text, duration, language, word/segment counts — not the full verbose payload)
4. Extend `set_observation_input()` to support dict-style keyword arguments for non-chat providers, in addition to the existing chat-style positional args

## Files to modify

| File | Change |
|------|--------|
| `episodes/providers/openai.py` | Add decorator, input/output logging |
| `episodes/observability.py` | Extend `set_observation_input` to support dict-style kwargs |
| `episodes/tests/test_observability.py` | Add tests for both calling conventions |
| `CHANGELOG.md` | Add entry under Fixed |
